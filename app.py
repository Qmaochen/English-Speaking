import streamlit as st
import speech_recognition as sr
from streamlit_mic_recorder import mic_recorder
from io import BytesIO
import edge_tts
import asyncio
import random
import pandas as pd
from groq import Groq
import re
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# --- 設定區 ---
# 記得把 API Key 設為空字串，強迫使用者輸入，或設為 st.secrets["GROQ_API_KEY"]
DEFAULT_API_KEY = "" 

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
        .stTextArea textarea {
            background-color: #fff9c4;
            color: #333;
        }
    </style>
    """, unsafe_allow_html=True)

# --- ☁️ Google Sheets 核心功能 ---

def get_db_connection():
    """建立 Google Sheets 連線"""
    return st.connection("gsheets", type=GSheetsConnection)

def load_data(worksheet_name):
    """從指定分頁讀取資料"""
    conn = get_db_connection()
    try:
        # ttl=0 確保每次都讀到最新的，不使用快取
        df = conn.read(worksheet=worksheet_name, ttl=0)
        return df
    except Exception as e:
        st.error(f"Error loading {worksheet_name}: {e}")
        return pd.DataFrame()

def save_weak_question_cloud(question):
    """將錯題寫入雲端 Weak_Questions 分頁"""
    conn = get_db_connection()
    try:
        df = conn.read(worksheet="Weak_Questions", ttl=0)
        
        # 檢查是否已存在
        if "Question" in df.columns and question not in df["Question"].values:
            new_row = pd.DataFrame({"Question": [question]})
            updated_df = pd.concat([df, new_row], ignore_index=True)
            conn.update(worksheet="Weak_Questions", data=updated_df)
            st.toast("Saved to Cloud Weak Qs! ☁️", icon="💾")
    except Exception as e:
        st.error(f"Cloud Save Error: {e}")

def save_score_history_cloud(question, scores):
    """將分數寫入雲端 Score_History 分頁"""
    conn = get_db_connection()
    try:
        df = conn.read(worksheet="Score_History", ttl=0)
        
        new_record = {
            "Date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "Question": question,
            "Fluency": scores["Fluency"],
            "Vocabulary": scores["Vocabulary"],
            "Grammar": scores["Grammar"],
            "Clarity": scores["Clarity"]
        }
        new_row = pd.DataFrame([new_record])
        updated_df = pd.concat([df, new_row], ignore_index=True)
        conn.update(worksheet="Score_History", data=updated_df)
    except Exception as e:
        st.error(f"History Save Error: {e}")

def get_previous_scores_cloud(question):
    """從雲端讀取上一次的分數"""
    try:
        conn = get_db_connection()
        df = conn.read(worksheet="Score_History", ttl=0)
        
        if df.empty or "Question" not in df.columns:
            return None
            
        # 篩選該題目的歷史紀錄
        history = df[df["Question"] == question]
        
        if len(history) >= 1:
            # 取最後一筆 (iloc[-1] 是最新的，但我們要比較的對象是"這次存入之前的最新")
            # 邏輯：因為我們剛剛已經存入了這次的分數，所以現在資料庫裡最新的一筆是"這次"，倒數第二筆是"上次"
            if len(history) >= 2:
                last_record = history.iloc[-2]
                return {
                    "Fluency": last_record["Fluency"],
                    "Vocabulary": last_record["Vocabulary"],
                    "Grammar": last_record["Grammar"],
                    "Clarity": last_record["Clarity"]
                }
        return None
    except:
        return None

# --- 其他輔助函式 ---

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
        system_prompt = """
        Act as a helpful, supportive English speaking tutor. 
        IMPORTANT: You cannot hear the audio. You can only see the transcript.
        Evaluate "Clarity" based on how coherent the transcript is.
        """
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
        (Provide a useful English sentence template/structure.)
        """
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.3, max_tokens=1024
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"⚠️ Groq API Error: {e}"

def parse_feedback_robust(text):
    result = {"scores": {"Fluency": 0, "Vocabulary": 0, "Grammar": 0, "Clarity": 0}, "feedback": "", "better_expression": "", "advice": ""}
    try:
        pattern = r"(\w+):\s*(\d+(\.\d+)?)"
        matches = re.findall(pattern, text)
        for key, value, _ in matches:
            if key in result["scores"]: result["scores"][key] = float(value)
    except: pass
    
    fb = re.search(r"### 📝 Feedback\s*(.*?)\s*###", text, re.DOTALL)
    if fb: result["feedback"] = fb.group(1).strip()
    be = re.search(r"### 💡 Better Expression\s*(.*?)\s*###", text, re.DOTALL)
    if be: result["better_expression"] = be.group(1).strip()
    ad = re.search(r"### 🔧 Advice.*?\)\s*(.*)", text, re.DOTALL)
    if not ad: ad = re.search(r"### 🔧 Advice\s*(.*)", text, re.DOTALL)
    if ad: result["advice"] = ad.group(1).strip()
    return result

async def generate_audio_bytes(text):
    communicate = edge_tts.Communicate(text, "en-US-AndrewNeural")
    temp_filename = "temp_tts_output.mp3"
    await communicate.save(temp_filename)
    with open(temp_filename, "rb") as f: audio_bytes = f.read()
    return audio_bytes

# Callback for Skip Topic
def skip_topic_callback():
    if st.session_state.questions_list:
        st.session_state.current_question = random.choice(st.session_state.questions_list)
        st.session_state.transcript = ""
        st.session_state.feedback = ""
        st.session_state.tts_audio_bytes = None
        st.session_state.scratchpad = ""

# --- 頁面主程式 ---

st.set_page_config(page_title="Speaking Tutor Pro (Cloud)", page_icon="☁️", layout="centered")
load_custom_css()

# Sidebar
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/4712/4712009.png", width=80)
    st.title("Settings")
    api_key_input = st.text_input("🔑 Groq API Key", value=DEFAULT_API_KEY, type="password")
    
    st.divider()
    
    # Mode Selection (Directly loading from Cloud)
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        if st.button("☁️ Normal"):
            with st.spinner("Loading from Cloud..."):
                df = load_data("Questions")
                if not df.empty:
                    st.session_state.questions_list = df['Question'].dropna().astype(str).tolist()
                    st.session_state.mode = "Normal"
                    skip_topic_callback() # Load a new question
                    st.rerun()
                else:
                    st.error("Failed to load 'Questions' tab.")
                    
    with col_s2:
        if st.button("☁️ Weak"):
            with st.spinner("Loading Weak Qs..."):
                df = load_data("Weak_Questions")
                if not df.empty:
                    st.session_state.questions_list = df['Question'].dropna().astype(str).tolist()
                    st.session_state.mode = "Weak Review"
                    skip_topic_callback()
                    st.rerun()
                else:
                    st.warning("No weak questions found in cloud.")

    st.caption(f"Mode: {st.session_state.get('mode', 'Normal')}")
    st.divider()
    st.info("Data is automatically saved to Google Sheets.")

# Initialization
if "questions_list" not in st.session_state:
    # Default fallback if not loaded yet
    st.session_state.questions_list = ["Describe a happy memory."] 
if "current_question" not in st.session_state:
    st.session_state.current_question = "Press a mode button to start!"
if "transcript" not in st.session_state: st.session_state.transcript = ""
if "feedback" not in st.session_state: st.session_state.feedback = ""
if "tts_audio_bytes" not in st.session_state: st.session_state.tts_audio_bytes = None

# UI Layout
st.title("☁️ AI Speaking Tutor")
st.markdown("Connected to **Google Sheets**. Practice anywhere, sync everywhere.")

# Question Card
st.markdown(f"""
<div class="question-card">
    <div style="color: #666; font-size: 14px; margin-bottom: 5px;">TOPIC ({st.session_state.get('mode', 'Wait')})</div>
    <div class="question-text">{st.session_state.current_question}</div>
</div>
""", unsafe_allow_html=True)

# Scratchpad
st.caption("📝 Scratchpad")
st.text_area("Scratchpad", height=68, key="scratchpad", label_visibility="collapsed")

# Buttons
col1, col2, col3 = st.columns([1, 2, 1], vertical_alignment="center")
with col1:
    st.button("🎲 Skip", use_container_width=True, on_click=skip_topic_callback)
with col2:
    audio_blob = mic_recorder(start_prompt="🔴 Record", stop_prompt="⏹️ Stop", key='recorder', format="wav")

# Processing
if audio_blob:
    st.audio(audio_blob['bytes'], format='audio/wav')
    with st.spinner("⚡ Cloud AI Analyzing..."):
        transcript = transcribe_audio(audio_blob['bytes'])
        if transcript:
            st.session_state.transcript = transcript
            if api_key_input:
                feedback = get_ai_feedback(api_key_input, st.session_state.current_question, transcript)
                st.session_state.feedback = feedback
                
                parsed = parse_feedback_robust(feedback)
                scores = parsed["scores"]
                
                # 1. Save History to Cloud
                save_score_history_cloud(st.session_state.current_question, scores)
                
                # 2. Check Weak Question & Save to Cloud
                avg = sum(scores.values()) / 4
                if avg < 6.0:
                    save_weak_question_cloud(st.session_state.current_question)
                
                # 3. Generate TTS
                clean_better = parsed["better_expression"].replace("*", "").strip()
                if len(clean_better) > 5:
                    st.session_state.tts_audio_bytes = asyncio.run(generate_audio_bytes(clean_better))
                else:
                    st.session_state.tts_audio_bytes = None
            else:
                st.error("Missing API Key")
        else:
            st.warning("No speech detected.")

# Results
if st.session_state.transcript:
    st.divider()
    st.markdown(f"""<div class="user-answer-box"><b>🗣️ You said:</b><br>{st.session_state.transcript}</div>""", unsafe_allow_html=True)

if st.session_state.feedback:
    data = parse_feedback_robust(st.session_state.feedback)
    scores = data["scores"]
    
    # Get previous scores from cloud for comparison
    prev = get_previous_scores_cloud(st.session_state.current_question)
    
    st.subheader("📊 Score & Cloud Sync")
    if prev: st.caption("Comparing with Cloud History (Green = Improved)")
    
    m1, m2, m3, m4 = st.columns(4)
    d_fl = scores["Fluency"] - prev["Fluency"] if prev else None
    d_vo = scores["Vocabulary"] - prev["Vocabulary"] if prev else None
    d_gr = scores["Grammar"] - prev["Grammar"] if prev else None
    d_cl = scores["Clarity"] - prev["Clarity"] if prev else None
    
    m1.metric("Fluency", f"{scores['Fluency']}", delta=d_fl, border=True)
    m2.metric("Vocab", f"{scores['Vocabulary']}", delta=d_vo, border=True)
    m3.metric("Grammar", f"{scores['Grammar']}", delta=d_gr, border=True)
    m4.metric("Clarity", f"{scores['Clarity']}", delta=d_cl, border=True)
    
    st.divider()
    t1, t2, t3 = st.tabs(["📝 Feedback", "💡 Better Expression", "🔧 Template"])
    with t1: st.markdown(data["feedback"])
    with t2: 
        st.success(data["better_expression"])
        if st.session_state.tts_audio_bytes: st.audio(st.session_state.tts_audio_bytes, format="audio/mp3")
    with t3: st.info(data["advice"])