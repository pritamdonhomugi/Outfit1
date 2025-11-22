from flask import Flask, request, jsonify, send_file
import requests
from PIL import Image
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
import os

app = Flask(__name__)

main_key = "PRITAMHERO"
executor = ThreadPoolExecutor(max_workers=10)

# Image positions and sizes
IMAGE_CONFIG = {
    "BACKGROUND": {"file": "output.png"},  # Local background file
    "OUTFIT_PARTS": [
        {"x": 110, "y": 85, "w": 120, "h": 120},
        {"x": 485, "y": 85, "w": 120, "h": 120},
        {"x": 565, "y": 215, "w": 120, "h": 120},
        {"x": 30, "y": 205, "w": 120, "h": 120},
        {"x": 35, "y": 373, "w": 110, "h": 110},
        {"x": 105, "y": 500, "w": 120, "h": 120},
        {"x": 505, "y": 515, "w": 100, "h": 100}
    ],
    "CHARACTER": {"x": 95, "y": 50, "w": 525, "h": 625},  # Character position box
    "WEAPONS": [
        {"x": 445, "y": 375, "w": 250, "h": 125}
    ]
}

ITEM_API = "https://ff-items-icon-info.vercel.app/item-image?id={itemid}&key=NRCODEX"

# Fetch player info
def fetch_player_info(uid, region):
    url = f'https://grandmixture-id-info.vercel.app/player-info?region={region}&uid={uid}'
    response = requests.get(url)
    return response.json() if response.status_code == 200 else None

# Download and process image from URL
def fetch_and_process_image(image_url, size=None, remove_bg=False):
    try:
        response = requests.get(image_url)
        if response.status_code == 200:
            image = Image.open(BytesIO(response.content)).convert("RGBA")
            if remove_bg:
                datas = image.getdata()
                new_data = []
                for item in datas:
                    r, g, b, a = item
                    if (r > 240 and g > 240 and b > 240) or a == 0:
                        new_data.append((255, 255, 255, 0))
                    else:
                        new_data.append(item)
                image.putdata(new_data)
            if size:
                image = image.resize(size, Image.LANCZOS)
            return image
    except Exception as e:
        print(f"Error processing image: {e}")
    return None

@app.route('/outfit-image', methods=['GET'])
def outfit_image():
    uid = request.args.get('uid')
    region = request.args.get('region')
    key = request.args.get('key')
    weapon_size = request.args.get('weapon_size', default=150, type=int)
    remove_bg = request.args.get('remove_bg', default='true').lower() == 'true'

    if not uid or not region:
        return jsonify({'error': 'Missing uid or region'}), 400
    if key != main_key:
        return jsonify({'error': 'Invalid or missing API key'}), 403

    bg_path = IMAGE_CONFIG["BACKGROUND"]["file"]
    if not os.path.exists(bg_path):
        return jsonify({'error': f'Background image {bg_path} not found'}), 500

    try:
        background_image = Image.open(bg_path).convert("RGBA")
    except Exception as e:
        return jsonify({'error': f'Failed to open background image: {str(e)}'}), 500

    player_data = fetch_player_info(uid, region)
    if not player_data:
        return jsonify({'error': 'Failed to fetch player info'}), 500

    outfit_ids = player_data.get("AccountProfileInfo", {}).get("EquippedOutfit", [])
    skills = player_data.get("AccountProfileInfo", {}).get("EquippedSkills", [])
    weapons = player_data.get("AccountInfo", {}).get("EquippedWeapon", [])

    # Outfit logic
    required_starts = ["211", "214", "211", "203", "204", "205", "203"]
    fallback_ids = ["211000000", "214000000", "208000000", "203000000", "204000000", "205000000", "212000000"]
    used_ids = set()

    def fetch_outfit_image(idx, code):
        matched = None
        for oid in outfit_ids:
            str_oid = str(oid)
            if str_oid.startswith(code) and oid not in used_ids:
                matched = oid
                used_ids.add(oid)
                break
        if matched is None:
            matched = fallback_ids[idx]
        image_url = ITEM_API.format(itemid=matched)
        return fetch_and_process_image(image_url, size=(150, 150))

    outfit_images = [executor.submit(fetch_outfit_image, idx, code) for idx, code in enumerate(required_starts)]

    for idx, future in enumerate(outfit_images):
        outfit_image = future.result()
        if outfit_image:
            pos = IMAGE_CONFIG["OUTFIT_PARTS"][idx]
            resized = outfit_image.resize((pos['w'], pos['h']), Image.LANCZOS)
            background_image.paste(resized, (pos['x'], pos['y']), resized)

    # ✅ Character logic (use second skill ID as character)
    if skills and len(skills) >= 2:
        char_id = skills[1]
        char_url = ITEM_API.format(itemid=char_id)
        char_image = fetch_and_process_image(char_url, remove_bg=remove_bg)
        if char_image:
            # Maintain aspect ratio within CHARACTER box
            orig_ratio = char_image.width / char_image.height
            box = IMAGE_CONFIG["CHARACTER"]
            target_ratio = box["w"] / box["h"]
            if orig_ratio > target_ratio:
                char_width = box["w"]
                char_height = int(char_width / orig_ratio)
            else:
                char_height = box["h"]
                char_width = int(char_height * orig_ratio)
            char_x = box["x"] + (box["w"] - char_width) // 2
            char_y = box["y"] + (box["h"] - char_height) // 2
            char_image = char_image.resize((char_width, char_height), Image.LANCZOS)
            background_image.paste(char_image, (char_x, char_y), char_image)

    # Weapons
    if weapons and isinstance(weapons, list):
        for idx, weapon_id in enumerate(weapons[:3]):
            if idx >= len(IMAGE_CONFIG["WEAPONS"]):
                break
            weapon_url = ITEM_API.format(itemid=weapon_id)
            weapon_image = fetch_and_process_image(weapon_url, size=(weapon_size, weapon_size), remove_bg=True)
            if weapon_image:
                pos = IMAGE_CONFIG["WEAPONS"][idx]
                resized = weapon_image.resize((pos['w'], pos['h']), Image.LANCZOS)
                background_image.paste(resized, (pos['x'], pos['y']), resized)

    img_io = BytesIO()
    background_image.save(img_io, 'PNG', optimize=True, quality=95)
    img_io.seek(0)

    return send_file(img_io, mimetype='image/png')

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)