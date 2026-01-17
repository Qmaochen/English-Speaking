import streamlit as st
import json
from streamlit_gsheets import GSheetsConnection

st.title("🕵️ 雲端身分偵探")

try:
    # 1. 檢查 Secrets 格式
    if "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
        st.success("✅ Secrets 結構正確 (Found [connections.gsheets])")
        
        # 2. 嘗試解析 JSON
        secret_info = st.secrets["connections"]["gsheets"]["service_account_info"]
        creds = json.loads(secret_info)
        
        bot_email = creds.get("client_email", "找不到 Email")
        st.info(f"🤖 機器人自稱是：\n\n**{bot_email}**")
        
        st.warning("👉 請複製上面這個 Email，去你的 Google Sheet 再檢查一次共用設定！")
        
        # 3. 嘗試連線
        conn = st.connection("gsheets", type=GSheetsConnection)
        # 加上 ttl=0 可以強迫它重新去雲端抓資料，不要讀舊紀錄
        # 不寫 worksheet="..."，預設就是抓第一頁 (Sheet1/Questions)
        df = conn.read(ttl=0) 
        st.dataframe(df)
        st.success("🎉 連線成功！讀取到資料了！")
        st.dataframe(df)

    else:
        st.error("❌ Secrets 結構錯誤！找不到 [connections.gsheets]")

except json.JSONDecodeError:
    st.error("❌ JSON 格式錯誤！你的 service_account_info 裡面可能有不該有的換行或缺引號。")
except Exception as e:
    st.error(f"❌ 連線失敗: {e}")