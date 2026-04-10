import time
import threading
import pandas as pd
import streamlit as st
import random
import math
from datetime import datetime
import pydeck as pdk
import numpy as np

# ========================= 心跳模拟器 =========================
class HeartbeatSimulator:
    def __init__(self):
        self.sequence = 0
        self.last_received_time = None
        self.timeout_threshold = 3
        self.heartbeat_data = []
        self.status_data = []
        self.running = False
        self.ground_station_online = True

    def send_heartbeat(self):
        while self.running:
            if self.ground_station_online or random.random() > 0.8:
                heartbeat = {
                    "sequence": self.sequence,
                    "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                    "status": "Received"
                }
                self.heartbeat_data.append(heartbeat)
                self.status_data.append({"time": datetime.now(), "value": 1})
                self.status_data.append({"time": datetime.now(), "value": 0})
                self.last_received_time = time.time()
                self.sequence += 1
            time.sleep(1)

    def check_timeout(self):
        while self.running:
            current_time = time.time()
            if (self.last_received_time and
                (current_time - self.last_received_time > self.timeout_threshold)):
                timeout_msg = {
                    "sequence": self.sequence,
                    "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                    "status": "Timeout!"
                }
                self.heartbeat_data.append(timeout_msg)
                self.status_data.append({"time": datetime.now(), "value": 2})
                self.status_data.append({"time": datetime.now(), "value": 0})
                self.sequence += 1
                self.last_received_time = time.time()
            time.sleep(0.1)

# ========================= 障碍物生成 =========================
def generate_obstacles(lat_min, lat_max, lng_min, lng_max, count=8):
    obstacles = []
    for i in range(count):
        lat = random.uniform(lat_min, lat_max)
        lng = random.uniform(lng_min, lng_max)
        height = random.uniform(5, 25)
        obstacles.append({
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "height": round(height, 1),
            "name": f"障碍物 {i+1}"
        })
    return obstacles

# ========================= 3D地图（默认底图，交互正常） =========================
def show_3d_map(point_a, point_b, obstacles, custom_polygon=None):
    center_lat = (point_a["lat"] + point_b["lat"]) / 2
    center_lng = (point_a["lng"] + point_b["lng"]) / 2

    view_state = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lng,
        zoom=16,
        pitch=45,
        bearing=0
    )

    # A点（绿）
    a_layer = pdk.Layer(
        "ScatterplotLayer",
        data=[point_a],
        get_position=["lng", "lat"],
        get_color=[0, 255, 0],
        get_radius=8,
        pickable=True
    )

    # B点（红）
    b_layer = pdk.Layer(
        "ScatterplotLayer",
        data=[point_b],
        get_position=["lng", "lat"],
        get_color=[255, 0, 0],
        get_radius=8,
        pickable=True
    )

    # 航线
    path = [[point_a["lng"], point_a["lat"]], [point_b["lng"], point_b["lat"]]]
    path_layer = pdk.Layer(
        "LineLayer",
        data=[{"path": path}],
        get_source_position="path[0]",
        get_target_position="path[1]",
        get_color=[255, 255, 0],
        get_width=3
    )

    # 障碍物柱状图
    obstacle_layer = pdk.Layer(
        "ColumnLayer",
        data=obstacles,
        get_position=["lng", "lat"],
        get_elevation="height",
        elevation_scale=1,
        radius=6,
        get_fill_color=[255, 165, 0],
        pickable=True
    )

    layers = [a_layer, b_layer, path_layer, obstacle_layer]

    # 自定义多边形
    if custom_polygon and len(custom_polygon) >= 3:
        polygon_layer = pdk.Layer(
            "PolygonLayer",
            data=[{"polygon": custom_polygon}],
            get_polygon="polygon",
            get_fill_color=[255, 0, 0, 100],
            get_line_color=[255, 0, 0],
            line_width_min_pixels=2,
            pickable=True
        )
        layers.append(polygon_layer)

    deck = pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        map_provider="carto",           # 免费底图，无需 Token
        map_style="light",
        tooltip={"text": "{name}\n高度: {height}m"}
    )

    st.pydeck_chart(deck)

# ========================= 主程序 =========================
def main():
    st.set_page_config(page_title="无人机监控系统", layout="wide")

    # 初始化会话状态
    if "simulator" not in st.session_state:
        st.session_state.simulator = HeartbeatSimulator()
    if "custom_polygon" not in st.session_state:
        st.session_state.custom_polygon = []  # [[lng, lat], ...]
    if "obstacles" not in st.session_state:
        # 默认障碍物生成范围（南京科技职业学院周边）
        LAT_MIN, LAT_MAX = 32.178, 32.183
        LNG_MIN, LNG_MAX = 118.625, 118.631
        st.session_state.obstacles = generate_obstacles(LAT_MIN, LAT_MAX, LNG_MIN, LNG_MAX)

    page = st.sidebar.radio("功能页面", ["航线规划", "飞行监控"])

    # ==================== 航线规划页面 ====================
    if page == "航线规划":
        st.title("🛰️ 无人机航线规划（自由选点 · 无需Token）")
        st.info("📍 默认坐标：南京科技职业学院 | 可任意修改经纬度")

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("A点（起飞点）")
            # 移除 min/max 限制，允许自由输入
            a_lat = st.number_input("A点纬度", value=32.1805, format="%.6f", key="a_lat")
            a_lng = st.number_input("A点经度", value=118.6278, format="%.6f", key="a_lng")
        with col2:
            st.subheader("B点（目标点）")
            b_lat = st.number_input("B点纬度", value=32.1810, format="%.6f", key="b_lat")
            b_lng = st.number_input("B点经度", value=118.6290, format="%.6f", key="b_lng")

        point_a = {"lat": a_lat, "lng": a_lng, "name": "A点"}
        point_b = {"lat": b_lat, "lng": b_lng, "name": "B点"}

        # 障碍物管理
        st.subheader("障碍物管理")
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("🔄 重新生成随机障碍物"):
                # 根据当前 A/B 点动态生成障碍物范围
                lat_min = min(a_lat, b_lat) - 0.005
                lat_max = max(a_lat, b_lat) + 0.005
                lng_min = min(a_lng, b_lng) - 0.005
                lng_max = max(a_lng, b_lng) + 0.005
                st.session_state.obstacles = generate_obstacles(lat_min, lat_max, lng_min, lng_max)
                st.rerun()
        with col_btn2:
            if st.button("🗑️ 清除自定义多边形"):
                st.session_state.custom_polygon = []
                st.rerun()

        # 多边形圈选（自由输入）
        with st.expander("✏️ 多边形圈选障碍区（自定义）", expanded=True):
            st.markdown("输入多边形顶点经纬度，至少3个点。")
            col_input, col_display = st.columns([2, 1])
            with col_input:
                new_lat = st.number_input("顶点纬度", value=32.1800, format="%.6f", key="poly_lat")
                new_lng = st.number_input("顶点经度", value=118.6280, format="%.6f", key="poly_lng")
                if st.button("➕ 添加顶点"):
                    st.session_state.custom_polygon.append([new_lng, new_lat])
                    st.rerun()
                if st.button("↩️ 撤销上一个顶点"):
                    if st.session_state.custom_polygon:
                        st.session_state.custom_polygon.pop()
                        st.rerun()
            with col_display:
                st.write("当前多边形顶点：")
                for i, pt in enumerate(st.session_state.custom_polygon):
                    st.write(f"{i+1}. ({pt[0]:.6f}, {pt[1]:.6f})")
                if len(st.session_state.custom_polygon) >= 3:
                    st.success("多边形已闭合")
                else:
                    st.warning("至少需要3个顶点")

        st.subheader("3D 地图")
        show_3d_map(point_a, point_b, st.session_state.obstacles, st.session_state.custom_polygon)

        st.subheader("障碍物数据")
        st.dataframe(pd.DataFrame(st.session_state.obstacles), use_container_width=True)

    # ==================== 飞行监控页面 ====================
    elif page == "飞行监控":
        st.title("✈️ 无人机心跳监控系统")
        simulator = st.session_state.simulator

        col1, col2 = st.columns(2)
        with col1:
            if st.button("▶️ 启动模拟"):
                simulator.running = True
                threading.Thread(target=simulator.send_heartbeat, daemon=True).start()
                threading.Thread(target=simulator.check_timeout, daemon=True).start()
                st.success("模拟已启动")
        with col2:
            if st.button("⏹️ 停止模拟"):
                simulator.running = False
                st.success("模拟已停止")

        st.sidebar.header("地面站控制")
        simulator.ground_station_online = st.sidebar.checkbox("地面站在线", value=True)
        if not simulator.ground_station_online:
            st.sidebar.warning("地面站离线，模拟信号丢失")

        status_placeholder = st.empty()
        chart_placeholder = st.empty()

        if simulator.running:
            latest = simulator.heartbeat_data[-1] if simulator.heartbeat_data else {}
            status_text = f"状态：{latest.get('status','待启动')} | 时间：{latest.get('timestamp','')}"
            status_placeholder.markdown(f"**{status_text}**")

            if simulator.status_data:
                df = pd.DataFrame(simulator.status_data[-50:])
                df['time'] = pd.to_datetime(df['time'])
                chart_placeholder.line_chart(df.set_index('time')['value'], height=300)

            time.sleep(0.5)
            st.rerun()
        else:
            if simulator.heartbeat_data:
                st.subheader("心跳日志")
                st.dataframe(pd.DataFrame(simulator.heartbeat_data), use_container_width=True)

if __name__ == "__main__":
    main()
