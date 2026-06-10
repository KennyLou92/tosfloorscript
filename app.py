import base64
import json
import requests
from flask import Flask, jsonify, render_template
from flask_cors import CORS
from Crypto.Cipher import ChaCha20

app = Flask(__name__)
CORS(app)

DEFAULT_URL = "https://cf.tosconfig.com/floorScripts/com.madhead.tos.zh/b943ba826e20e5ce276666a896b5bfd2-index.data"
encoded_key = "Hw0QCtCMy2SQ91gDNh813jeKXSGfrRvzN1UOIPKIRKY="
KEY = base64.b64decode(encoded_key)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7'
}

cached_floor_scripts = []
cached_base_url = ""

def chacha20_decrypt(key, nonce, ciphertext):
    cipher = ChaCha20.new(key=key, nonce=nonce)
    return cipher.decrypt(ciphertext)

def init_index_data():
    global cached_floor_scripts, cached_base_url
    if cached_floor_scripts:
        return
    ciphertext = requests.get(DEFAULT_URL, headers=HEADERS, timeout=10).content
    filesize = len(ciphertext)
    nonce = filesize.to_bytes(8, "little")
    plaintext = chacha20_decrypt(KEY, nonce, ciphertext)
    
    parsed_json = json.loads(plaintext)
    cached_floor_scripts = parsed_json.get("floorScripts", [])
    cached_base_url = parsed_json.get("baseUrl", "")

def format_text_to_html(text):
    if not text:
        return ""
    return str(text).replace("\r\n", "<br>").replace("\r", "<br>").replace("\n", "<br>")

def parse_string_script(script_str):
    """處理早期舊版字串格式 (969~名字~對話)"""
    lines = []
    raw_lines = script_str.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for line in raw_lines:
        line = line.strip()
        if not line: continue
        
        parts = line.split("~")
        if len(parts) >= 3:
            name = parts[1].strip()
            dialog = "~".join(parts[2:]).strip()
            if dialog:
                dialog_html = format_text_to_html(dialog)
                if name == "" or name == "  " or name == " \t\t":
                    lines.append(f'<div class="dialog-row-plain">{dialog_html}</div>')
                else:
                    name_html = format_text_to_html(name)
                    lines.append(f'<div class="dialog-row"><span class="speaker">{name_html}:</span> <span class="words">{dialog_html}</span></div>')
        else:
            dialog_html = format_text_to_html(line)
            lines.append(f'<div class="dialog-row-plain">{dialog_html}</div>')
    return lines

def extract_dialogs_recursive(data, lang="zh"):
    """
    處理後期 Dict/List 嵌套格式 (已修正：支援動態提取中英文欄位)
    """
    results = []
    
    # 依據語系決定讀取哪一個 JSON 鍵值
    dialog_key = "dialogEn" if lang == "en" else "dialog"
    name_key = "displayNameEn" if lang == "en" else "displayName"
    
    if isinstance(data, dict):
        # 只要該物件內含有指定的對話內容，不論中英文都撈出來
        if dialog_key in data and data[dialog_key]:
            name = str(data.get(name_key, "")).strip()
            dialog = str(data[dialog_key]).strip()
            dialog_html = format_text_to_html(dialog)
            
            # 處理全形空格或空白旁白
            if name == "" or name == "  " or name == " ":
                results.append(f'<div class="dialog-row-plain">{dialog_html}</div>')
            else:
                name_html = format_text_to_html(name)
                results.append(f'<div class="dialog-row"><span class="speaker">{name_html}:</span> <span class="words">{dialog_html}</span></div>')
        else:
            # 繼續深度遞迴搜尋
            for key, value in data.items():
                results.extend(extract_dialogs_recursive(value, lang))
                
    elif isinstance(data, list):
        for item in data:
            results.extend(extract_dialogs_recursive(item, lang))
            
    return results

def build_html_from_fields(container, fields_config, lang="zh"):
    """根據指定的欄位順序與語言生成 HTML 區塊"""
    html_blocks = []
    for field_name, field_title in fields_config:
        if field_name in container:
            field_data = container[field_name]
            field_lines = []
            
            if isinstance(field_data, str):
                # 如果是早期字串型態，直接走字串解析
                field_lines = parse_string_script(field_data)
            else:
                # 如果是後期 List 嵌套型態，走動態語系的深度遞迴
                field_lines = extract_dialogs_recursive(field_data, lang)
                
            if field_lines:
                block_content = "".join(field_lines)
                html_blocks.append(f'<div class="story-section"><h3 class="section-title">{field_title}</h3>{block_content}</div>')
                
    return "".join(html_blocks) if html_blocks else None

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/floors', methods=['GET'])
def get_floors():
    try:
        init_index_data()
        floor_ids = [str(item["floorId"]).strip() for item in cached_floor_scripts]
        return jsonify({"success": True, "floors": floor_ids})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/story/<floor_id>', methods=['GET'])
def get_single_story(floor_id):
    try:
        init_index_data()
        search_id = str(floor_id).strip()
        
        target_item = None
        for x in cached_floor_scripts:
            if str(x.get("floorId", "")).strip() == search_id:
                target_item = x
                break
                
        if not target_item:
            return jsonify({"success": False, "error": f"找不到章節 ID: {search_id}"}), 404
            
        md5 = target_item["md5"]
        actual_id = target_item["floorId"]
        story_url = f"{cached_base_url}/{md5}-{actual_id}.json"
        
        res = requests.get(story_url, headers=HEADERS, timeout=10)
        res.raise_for_status()
        story_data = res.json()
        
        # 穿透到 stageDrama
        drama_container = story_data.get("stageDrama", {})
        if not drama_container or not isinstance(drama_container, dict):
            drama_container = story_data
            
        # 中文版欄位配置 (包含舊版單數、新版複數型態)
        zh_fields = [
            ("enterScript", "🎬 [進入關卡劇情]"),
            ("startScript", "📌 [開場劇情]"), ("startScripts", "📌 [開場劇情]"),
            ("waveScript", "⚔️ [波次特定劇情]"),
            ("bossScript", "👹 [Boss 登場劇情]"), ("bossScripts", "👹 [Boss 登場劇情]"),
            ("clearScript", "🏆 [通關劇情]"),
            ("endScript", "🏁 [結尾劇情]"), ("endScripts", "🏁 [結尾劇情]"),
            ("gameOverScript", "💀 [遊戲結束劇情]"), ("gameOverScripts", "💀 [遊戲結束劇情]")
        ]
        
        # 英文版欄位配置
        # 註：新版(如10313)它的複數欄位依然叫 "startScripts"，只是裡面的 key 變成了 dialogEn
        # 舊版(如2987)則是獨立欄位叫 "startScript_en"。這裡我們兩個都列入阻截！
        en_fields = [
            ("enterScript_en", "🎬 [Stage Entrance]"), ("enterScript", "🎬 [Stage Entrance]"),
            ("startScript_en", "📌 [Opening Story]"), ("startScripts", "📌 [Opening Story]"),
            ("waveScript_en", "⚔️ [Wave Specific Story]"), ("waveScript", "⚔️ [Wave Specific Story]"),
            ("bossScript_en", "👹 [Boss Appearance]"), ("bossScripts", "👹 [Boss Appearance]"),
            ("clearScript_en", "🏆 [Stage Clear Story]"), ("clearScript", "🏆 [Stage Clear Story]"),
            ("endScript_en", "🏁 [Ending Story]"), ("endScripts", "🏁 [Ending Story]"),
            ("gameOverScript_en", "💀 [Game Over Story]"), ("gameOverScripts", "💀 [Game Over Story]")
        ]
        
        # 生成 HTML 文本
        zh_html = build_html_from_fields(drama_container, zh_fields, lang="zh")
        en_html = build_html_from_fields(drama_container, en_fields, lang="en")
        
        # 兜底防空字串機制
        if not zh_html:
            zh_html = '<div class="no-story">(該章節無中文對話劇本內容)</div>'
        if not en_html:
            en_html = '<div class="no-story">(該章節無英文對話劇本內容)</div>'
        
        return jsonify({
            "success": True, 
            "zh": zh_html,
            "en": en_html
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

import os

if __name__ == '__main__':
    # 讓程式能自動讀取雲端環境分配的 Port，若在本地端執行則預設為 5000
    port = int(os.environ.get("PORT", 5000))
    # 必須將 host 改為 0.0.0.0，雲端平台才能對外公開網頁
    app.run(host='0.0.0.0', port=port)