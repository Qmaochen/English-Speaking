import streamlit as st
import speech_recognition as sr
from streamlit_mic_recorder import mic_recorder
from io import BytesIO
import edge_tts
import asyncio
import os
import random
import pandas as pd
from groq import Groq
import re
import json
from datetime import datetime

# --- 設定區 ---
DEFAULT_API_KEY = "" 
EXCEL_FILE = "Questions.xlsx"
WEAK_FILE = "Weak_Questions.csv"
HISTORY_FILE = "score_history.json" # [新增] 歷史紀錄檔

# --- 💅 CSS 美化樣式 ---
def load_custom_css():
    st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        .question-card {
            background-color: #f0f2f6;
            border-left: 5px solid #ff4b4b;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 2px 2px 5px rgba(0,0,0,0.1);
        }
        .question-text {
            font-size: 24px;
            font-weight: bold;
            color: #1f1f1f;
        }
        .user-answer-box {
            background-color: #e8f4f9;
            border: 1px solid #d1e7ef;
            padding: 15px;
            border-radius: 10px;
            color: #0c5460;
            font-style: italic;
            margin-bottom: 20px;
        }
        .stButton button {
            height: 44px;
        }
    </style>
    """, unsafe_allow_html=True)

# --- 核心功能函式 ---

def load_questions(source="excel"):
    file_path = EXCEL_FILE if source == "excel" else WEAK_FILE
    try:
        if source == "excel":
            df = pd.read_excel(file_path)
            col_name = 'Question'
        else:
            if not os.path.exists(file_path): return []
            df = pd.read_csv(file_path)
            col_name = 'Question'
            
        if col_name in df.columns:
            return df[col_name].dropna().astype(str).tolist()
        return []
    except:
        return []

def save_weak_question(question):
    if not os.path.exists(WEAK_FILE):
        df = pd.DataFrame({"Question": [question]})
        df.to_csv(WEAK_FILE, index=False)
    else:
        df = pd.read_csv(WEAK_FILE)
        if question not in df['Question'].values:
            new_row = pd.DataFrame({"Question": [question]})
            df = pd.concat([df, new_row], ignore_index=True)
            df.to_csv(WEAK_FILE, index=False)

# [新增] 儲存分數歷史
def save_score_history(question, scores):
    history = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except:
            pass # 檔案損壞或空的，就重新建立
    
    if question not in history:
        history[question] = []
    
    # 加入時間戳記
    record = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "scores": scores
    }
    history[question].append(record)
    
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=4)

# [新增] 取得上一次的分數
def get_previous_scores(question):
    if not os.path.exists(HISTORY_FILE):
        return None
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        
        records = history.get(question, [])
        # 如果只有一筆紀錄(就是剛剛存的那筆)，代表沒有"上一次"，回傳 None
        # 如果有兩筆以上，回傳倒數第二筆 (因為倒數第一筆是剛剛存的)
        if len(records) >= 2:
            return records[-2]["scores"]
        else:
            return None
    except:
        return None

def transcribe_audio(audio_bytes):
    r = sr.Recognizer()
    try:
        with sr.AudioFile(BytesIO(audio_bytes)) as source:
            audio_data = r.record(source)
            text = r.recognize_google(audio_data, language='en-US')
            return text
    except:
        return None

def get_ai_feedback(api_key, question, user_text):
    try:
        client = Groq(api_key=api_key)
        
        # System Prompt
        system_prompt = """
        Act as a helpful, supportive English speaking tutor. 
        IMPORTANT: You cannot hear the audio. You can only see the transcript.
        Evaluate "Clarity" based on how coherent the transcript is.
        
        Your Goals:
        1. Rate leniently. Focus on communication intelligibility.
        2. In "Better Expression", DO NOT rewrite the whole paragraph. Keep the user's style. Just fix grammar.
        3. In "Advice", provide a SENTENCE TEMPLATE (Pattern).
        """

        # User Prompt: [修改 Advice 部分]
        user_prompt = f"""
        Topic: "{question}"
        User Answer: "{user_text}"
        
        Please output the response in this exact format:
        
        [SCORES]
        Fluency: <score 0-10>
        Vocabulary: <score 0-10>
        Grammar: <score 0-10>
        Clarity: <score 0-10>
        [/SCORES]

        ### 📝 Feedback
        (Give 2-3 brief, encouraging bullet points.)

        ### 💡 Better Expression
        (Modify the user's sentence MINIMALLY. Just fix grammar. Add punctuation.)

        ### 🔧 Advice (Template)
        (Provide a useful English sentence template/structure that the user can use to answer this question better next time. e.g., "One main advantage of X is that...")
        """

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=1024
        )
        
        return completion.choices[0].message.content

    except Exception as e:
        return f"⚠️ Groq API Error: {e}"

# [修改] 更強壯的解析函式 (解決 Parsing Error)
def parse_feedback_robust(text):
    result = {
        "scores": {"Fluency": 0, "Vocabulary": 0, "Grammar": 0, "Clarity": 0},
        "feedback": "No feedback found.",
        "better_expression": "No better expression found.",
        "advice": "No advice found."
    }
    
    # 1. 解析分數
    try:
        pattern = r"(\w+):\s*(\d+(\.\d+)?)"
        matches = re.findall(pattern, text)
        for key, value, _ in matches:
            if key in result["scores"]:
                result["scores"][key] = float(value)
    except:
        pass

    # 2. 解析各區塊 (使用 Regex 比較保險，不怕換行符號跑掉)
    # flag=re.DOTALL 讓 . 可以匹配換行符號
    
    # 抓 Feedback
    fb_match = re.search(r"### 📝 Feedback\s*(.*?)\s*###", text, re.DOTALL)
    if fb_match:
        result["feedback"] = fb_match.group(1).strip()
    
    # 抓 Better Expression
    be_match = re.search(r"### 💡 Better Expression\s*(.*?)\s*###", text, re.DOTALL)
    if be_match:
        result["better_expression"] = be_match.group(1).strip()
        
    # 抓 Advice (抓到最後)
    ad_match = re.search(r"### 🔧 Advice.*?\)\s*(.*)", text, re.DOTALL)
    if not ad_match:
        # 備用方案：如果標題稍微不一樣
        ad_match = re.search(r"### 🔧 Advice\s*(.*)", text, re.DOTALL)
        
    if ad_match:
        result["advice"] = ad_match.group(1).strip()

    return result

async def _edge_tts_save(text, filename):
    communicate = edge_tts.Communicate(text, "en-US-AndrewNeural")
    await communicate.save(filename)

def play_tts(text):
    temp_file = "temp_feedback.mp3"
    asyncio.run(_edge_tts_save(text, temp_file))
    st.audio(temp_file)

# --- 頁面主程式 ---

st.set_page_config(page_title="Speaking Tutor Pro", page_icon="📈", layout="centered")
load_custom_css()

# Sidebar
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/4712/4712009.png", width=80)
    st.title("Settings")
    api_key_input = st.text_input("🔑 Groq API Key", value=DEFAULT_API_KEY, type="password")
    
    st.divider()
    
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        if st.button("📂 Normal"):
            st.session_state.questions_list = load_questions("excel")
            st.session_state.mode = "Normal"
            st.rerun()
    with col_s2:
        if st.button("❤️ Weak Qs"):
            qs = load_questions("weak")
            if not qs:
                st.toast("No weak questions yet!", icon="⚠️")
            else:
                st.session_state.questions_list = qs
                st.session_state.mode = "Weak Review"
                st.rerun()

    st.caption(f"Current Mode: {st.session_state.get('mode', 'Normal')}")

# 初始化
if "questions_list" not in st.session_state:
    st.session_state.questions_list = load_questions("excel")
if "current_question" not in st.session_state:
    st.session_state.current_question = random.choice(st.session_state.questions_list) if st.session_state.questions_list else "No Question"
if "transcript" not in st.session_state:
    st.session_state.transcript = ""
if "feedback" not in st.session_state:
    st.session_state.feedback = ""

# --- UI ---

st.title("📈 AI Speaking Tutor")
st.markdown("Practice, Track Progress, and Improve.")

# 1. 題目
st.markdown(f"""
<div class="question-card">
    <div style="color: #666; font-size: 14px; margin-bottom: 5px;">CURRENT TOPIC ({st.session_state.get('mode', 'Normal')})</div>
    <div class="question-text">{st.session_state.current_question}</div>
</div>
""", unsafe_allow_html=True)

# 2. 按鈕
col1, col2, col3 = st.columns([1, 2, 1], vertical_alignment="center")

with col1:
    if st.button("🎲 Skip Topic", use_container_width=True):
        if st.session_state.questions_list:
            st.session_state.current_question = random.choice(st.session_state.questions_list)
            st.session_state.transcript = ""
            st.session_state.feedback = ""
            st.rerun()

with col2:
    audio_blob = mic_recorder(start_prompt="🔴 Record", stop_prompt="⏹️ Stop", key='recorder', format="wav")

with col3:
    pass

# 3. 處理
if audio_blob:
    st.audio(audio_blob['bytes'], format='audio/wav') # 回放自己聲音
    
    with st.spinner("⚡ Tutor is analyzing & saving history..."):
        transcript = transcribe_audio(audio_blob['bytes'])
        if transcript:
            st.session_state.transcript = transcript
            if api_key_input:
                feedback = get_ai_feedback(api_key_input, st.session_state.current_question, transcript)
                st.session_state.feedback = feedback
                
                # [新增] 儲存分數到歷史紀錄
                parsed = parse_feedback_robust(feedback)
                save_score_history(st.session_state.current_question, parsed["scores"])
                
            else:
                st.error("Please enter Groq API Key")
        else:
            st.warning("No speech detected. (Try speaking louder)")

# 4. 結果展示
if st.session_state.transcript:
    st.divider()
    st.markdown(f"""
    <div class="user-answer-box">
        <b>🗣️ You said:</b><br>
        {st.session_state.transcript}
    </div>
    """, unsafe_allow_html=True)

if st.session_state.feedback:
    # 使用新的 Robust 解析器
    data = parse_feedback_robust(st.session_state.feedback)
    scores = data["scores"]
    
    # 錯題本邏輯
    avg_score = sum(scores.values()) / 4 if scores else 0
    if avg_score > 0 and avg_score < 6.0:
        save_weak_question(st.session_state.current_question)
        st.toast(f"Low score ({avg_score:.1f}). Saved to Weak Questions!", icon="💾")

    # [新增] 取得上一次分數並計算 Delta
    prev_scores = get_previous_scores(st.session_state.current_question)
    
    st.subheader("📊 Score & Progress")
    if prev_scores:
        st.caption("Comparing with your last attempt (Green = Improved)")
    else:
        st.caption("First time recording this question.")

    m1, m2, m3, m4 = st.columns(4)
    
    # 計算 Delta (如果沒有上次分數，Delta 就是 None)
    d_fluency = scores["Fluency"] - prev_scores["Fluency"] if prev_scores else None
    d_vocab = scores["Vocabulary"] - prev_scores["Vocabulary"] if prev_scores else None
    d_grammar = scores["Grammar"] - prev_scores["Grammar"] if prev_scores else None
    d_clarity = scores["Clarity"] - prev_scores["Clarity"] if prev_scores else None

    m1.metric("Fluency", f"{scores['Fluency']}", delta=d_fluency, border=True)
    m2.metric("Vocab", f"{scores['Vocabulary']}", delta=d_vocab, border=True)
    m3.metric("Grammar", f"{scores['Grammar']}", delta=d_grammar, border=True)
    m4.metric("Clarity", f"{scores['Clarity']}", delta=d_clarity, border=True)

    st.markdown("---")
    
    tab1, tab2, tab3 = st.tabs(["📝 Feedback", "💡 Better Expression", "🔧 Template"])

    with tab1:
        st.markdown(data["feedback"])
    
    with tab2:
        st.success(data["better_expression"])
        clean_better = data["better_expression"].replace("*", "").strip()
        if len(clean_better) > 5:
            if st.button("🔊 Listen to Fix"):
                play_tts(clean_better)
            
    with tab3:
        # 這裡會顯示英文的 Template
        st.info(data["advice"])