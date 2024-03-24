from flask import Flask, request, jsonify
import json
import threading
import requests
import sqlite3
from openai import OpenAI
import setproctitle
import time



#==================环境变量（开始）===================================
# 机器人token
TOKEN = ""

# 黑名单(示例："0000000","0000001")
group_ban = [] # 群组
user_ban = []  # 用户

# 群组被at关键词
group_at = ["@Gemini", "@gemini", "@Gemini Bot", "@gemini bot", "@Gemini bot", "@bot", "@Bot", "#Bot", "/Bot", "#bot", "/bot"]

# OpenAI API的基本URL和API密钥
OPENAI_BASE_URL = "" #api接口地址：https://api.openai.com/v1
OPENAI_API_KEY = ""  #apikey：sk-xxxxxxxx
#调用模型
GPTmodel="gemini-1.0-pro-latest"

#==================环境变量（结束）===================================

app = Flask(__name__)

def yhchat_push(recvId,recvType,contentType,text):
    url = f"https://chat-go.jwzhd.com/open-apis/v1/bot/send?token={TOKEN}"
    # 构建推送消息的payload
    payload = json.dumps({
        "recvId": recvId,
        "recvType": recvType,
        "contentType": contentType,
        "content": {
            "text": text,
            "buttons": [
                [
                    {
                        "text": "复制",
                        "actionType": 2,
                        "value": text
                    },
                ]
            ]
        }
    })
    headers = {
        'Content-Type': 'application/json'
    }

    # 发送POST请求推送消息
    response = requests.request("POST", url, headers=headers, data=payload)

    json_msgId = json.loads(response.text)
    msgId = json_msgId['data']['messageInfo']['msgId']

    return msgId

#消息编辑api，用于流式输出
def yhchat_remsg(recvId,recvType,contentType,text,msgId):
    url = 'https://chat-go.jwzhd.com/open-apis/v1/bot/edit'
    headers = {
        'Content-Type': 'application/json'
    }
    data = {
        "msgId": msgId,
        "recvId": recvId,
        "recvType": recvType,
        "contentType": contentType,
        "content": {
            "text": text,
            "buttons": [
                [
                    {
                        "text": "复制",
                        "actionType": 2,
                        "value": text
                    },
                ]
            ]
        }
    }
    params = {
        'token': TOKEN
    }

    response = requests.post(url, headers=headers, json=data, params=params)
    return response.text

# 推送消息函数，将机器人的回复推送给指定的接收者
def push_message(recvType, recvId, contentType, text):
    
    msgId = yhchat_push(recvId,recvType,contentType,"…………")
    # 使用OpenAI进行对话生成

    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    stream = client.chat.completions.create(
        model=GPTmodel,
        messages=[
            {
                "role": "system",
                "content": "请使用简体中文进行回答",
            },
            {
                "role": "user",
                "content": text,
            }
        ],
        stream=True,
    )

    text_ok = ""
    for chunk in stream:
        if chunk.choices[0].delta.content is not None:
            time.sleep(0.3)
            text_1 = chunk.choices[0].delta.content
            text_ok += text_1
            yhchat_remsg(recvId,recvType,contentType,text_ok,msgId)
    
def process_messages(parsed_data):
    messages = []
    
    for message in parsed_data['data']['list']:
        if 'text' in message['content']:
            content_text = message['content']['text']
            if message['senderType'] == 'user':
                messages.append(f"user: {content_text}")
            elif message['senderType'] == 'bot':
                messages.append(f"assistant: {content_text}")
    
    messages.reverse()

    return '\n'.join(messages)

def messages_list(chat_id, message_id):
    # 设置访问 API 所需的参数和头部
    after = 60

    # 发送 GET 请求获取消息列表
    response = requests.get(
        'https://chat-go.jwzhd.com/open-apis/v1/bot/messages',
        params={'token': TOKEN, 'chat-id': chat_id, 'chat-type': 'user', 'message-id': message_id, 'after': after},
    )

    # 调用消息处理函数进行处理
    messages = process_messages(response.json())
    
    # 返回按照原始顺序排列的消息内容字符串
    return messages

def messages_sql(senderId, message_id_tmp, text_messages_list_tmp):
    # 连接到 SQLite 数据库（如果不存在，则会自动创建）
    conn = sqlite3.connect('messages_sql.db')
    cursor = conn.cursor()

    # 1. 检测text_messages_list_tmp值是否等于"/RESET"
    if text_messages_list_tmp == "/RESET" or text_messages_list_tmp == "/清除上下文":
        # 调用函数 push_message("user", senderId, "markdown", "上下文已清除！")
        yhchat_push(senderId,"user","text","上下文已清除")
        print("上下文已清除")
        # 删除以 senderId 命名的表
        cursor.execute(f"DROP TABLE IF EXISTS '{senderId}'")
        conn.commit()
        # 返回 "clean_text"
        return "clean_text"
        
    # 2. 检测当前数据库是否有以 senderId 值命名的表
    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{senderId}'")
    table_exists = cursor.fetchone()

    if not table_exists:
        # 创建以 senderId 命名的表
        cursor.execute(f"CREATE TABLE '{senderId}' (message_id TEXT, count INTEGER)")
        # 将 message_id_tmp 写入表的第一项并将第二项赋值为1
        cursor.execute(f"INSERT INTO '{senderId}' (message_id, count) VALUES (?, ?)", (message_id_tmp, 1))
        conn.commit()
        # 返回 message_id_tmp 的内容
        return message_id_tmp

    # 3. 提取第二项的数字
    cursor.execute(f"SELECT count FROM '{senderId}'")
    count = cursor.fetchone()[0]

    if count > 30:
        # 删除以 senderId 命名的表
        cursor.execute(f"DROP TABLE IF EXISTS '{senderId}'")
        conn.commit()
        yhchat_push(senderId,"user","text","上下文达到限制，已自动清除")
        return "clean_text"
    else:
        # 在表内的第二项数值的基础上加1
        cursor.execute(f"UPDATE '{senderId}' SET count = count + 1")
        # 提取以 senderId 值命名的表里的第一项赋值到 message_id
        cursor.execute(f"SELECT message_id FROM '{senderId}'")
        message_id = cursor.fetchone()[0]
        conn.commit()
        # 返回 message_id 的内容
        return message_id

# 处理消息函数，解析消息并调用推送消息函数
def handle_message(parsed_json):

    # print(f"json：{parsed_json}")
    senderType_tmp = parsed_json['event']['chat']['chatType']

    if senderType_tmp == "bot":  
        senderType = "user"
        print(f"类型：{senderType}")
        senderId = parsed_json['event']['sender']['senderId']
        print(f"用户ID：{senderId}")

        if senderId in user_ban:
            yhchat_push(senderId,"user","text","已被列入黑名单，请联系管理员！")
            print("黑名单用户，丢弃该消息！")
            return

        message_id_tmp = parsed_json['event']['message']['msgId']
        print(f"消息ID：{message_id_tmp}")
        
        text_messages_list_tmp = parsed_json['event']['message']['content']['text'] #处理用户输入的文本

        if text_messages_list_tmp == 'clean_text':
            print("丢弃该消息！")
            return
        message_id = messages_sql(senderId,message_id_tmp,text_messages_list_tmp)
        text = messages_list(senderId,message_id) #合成上下文

    if senderType_tmp == "group":  
        senderType = "group"
        print(f"类型：{senderType}")
        senderId = parsed_json['event']['chat']['chatId']
        print(f"群组ID：{senderId}")
        text = parsed_json['event']['message']['content']['text']

        if senderId in group_ban:
            yhchat_push(senderId,"user","text","该群组已被列入黑名单，请联系管理员！")
            print("黑名单群组，丢弃该消息！")
            return

        # 群组被at回复
        for item in group_at:
            if text.startswith(item):
                print(f"检测到被at: {item}")
                break
        else:  
            print("丢弃该消息！")
            return
    
        # 使用多线程调用推送消息函数，防止阻塞主线程
    threading.Thread(target=push_message, args=(senderType, senderId, "markdown", text)).start()

    
# Flask接收消息的路由，使用POST方法接收消息
@app.route('/yhchat', methods=['POST'])
def receive_message():
    try:
        # 解析收到的JSON数据
        json_data = request.get_json()

        # 处理消息
        handle_message(json_data)

        # 返回处理成功的响应
        return jsonify({'status': 'success'}), 200

    except Exception as e:
        print("Error:", e)
        # 返回处理失败的响应
        return jsonify({'status': 'error', 'message': str(e)}), 500

# 主函数，运行Flask应用
if __name__ == '__main__':
    setproctitle.setproctitle("yhchatBot_Gemini-Bot")
    app.run(host='0.0.0.0', port=56667)
