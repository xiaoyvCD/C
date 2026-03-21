#小组作业 无人机心跳模拟系统
import time
import threading
import pandas as pd
import streamlit as st
from datetime import datetime

class HeartbeatSimulator:
    def __init__(self):
        self.sequence = 0
        self.last_received_time = None
        self.timeout_threshold = 3  # 超时阈值（秒）
        self.heartbeat_data = []
        self.status_data = []  # 专门存储状态数据用于折线图
        self.running = False
        self.ground_station_online = True  # 地面站连接状态

    def send_heartbeat(self):
        while self.running:
            # 模拟地面站接收情况（随机丢失信号）
            if self.ground_station_online or random.random() > 0.8:  # 80%概率丢失信号
                heartbeat = {
                    "sequence": self.sequence,
                    "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                    "status": "Received"
                }
                self.heartbeat_data.append(heartbeat)
                self.status_data.append({"time": datetime.now(), "value": 1})  # 接收信号=1
                self.status_data.append({"time": datetime.now(), "value": 0})  # 回到初始状态
                self.last_received_time = time.time()
                self.sequence += 1
            time.sleep(1)

    def check_timeout(self):
        while self.running:
            current_time = time.time()
            
            # 地面站掉线检测
            if (self.last_received_time and 
                (current_time - self.last_received_time > self.timeout_threshold)):
                timeout_msg = {
                    "sequence": self.sequence,
                    "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                    "status": "Timeout!"
                }
                self.heartbeat_data.append(timeout_msg)
                self.status_data.append({"time": datetime.now(), "value": 2})  # 超时=2
                self.status_data.append({"time": datetime.now(), "value": 0})  # 回到初始状态
                self.sequence += 1
                self.last_received_time = time.time()  # 重置防止连续报超时
            
            time.sleep(0.1)

def main():
    st.title("✈️ 无人机心跳监控系统 (地面站版)")
    simulator = HeartbeatSimulator()

    # 控制面板
    col1, col2 = st.columns(2)
    with col1:
        if st.button("▶️ 启动模拟"):
            simulator.running = True
            sender_thread = threading.Thread(target=simulator.send_heartbeat)
            checker_thread = threading.Thread(target=simulator.check_timeout)
            sender_thread.start()
            checker_thread.start()
            st.success("模拟已启动")

    with col2:
        if st.button("⏹️ 停止模拟"):
            simulator.running = False
            st.success("模拟已停止")

    # 地面站控制
    st.sidebar.header("地面站控制")
    simulator.ground_station_online = st.sidebar.checkbox("地面站在线", value=True)
    
    if not simulator.ground_station_online:
        st.sidebar.warning("地面站离线状态，将模拟信号丢失")

    # 状态显示区域
    status_placeholder = st.empty()
    chart_placeholder = st.empty()

    # 主显示循环
    while simulator.running:
        # 更新状态文本
        latest = simulator.heartbeat_data[-1] if simulator.heartbeat_data else {}
        status_text = f"当前状态: {latest.get('status', '待启动')} | 最后心跳: {latest.get('timestamp', '')}"
        status_placeholder.markdown(f"**{status_text}**")

        # 更新折线图
        if simulator.status_data:
            df = pd.DataFrame(simulator.status_data[-50:])  # 只显示最近50个数据点
            df['time'] = pd.to_datetime(df['time'])
            chart_placeholder.line_chart(
                df.set_index('time')['value'],
                height=300,
                use_container_width=True
            )

        time.sleep(0.1)

    # 模拟停止后显示完整数据
    if simulator.heartbeat_data:
        st.subheader("事件日志")
        st.dataframe(pd.DataFrame(simulator.heartbeat_data))

        st.subheader("状态变化趋势")
        full_df = pd.DataFrame(simulator.status_data)
        full_df['time'] = pd.to_datetime(full_df['time'])
        st.line_chart(
            full_df.set_index('time')['value'],
            height=400,
            use_container_width=True
        )

if __name__ == "__main__":
    import random  # 用于模拟随机信号丢失
    main()

