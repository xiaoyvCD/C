import time
import threading
import pandas as pd
import streamlit as st
import random
from datetime import datetime
import pydeck as pdk
import numpy as np

# -------------------------- 坐标工具类（坐标系转换）--------------------------
class CoordinateTransformer:
    """WGS84经纬度与屏幕坐标转换工具"""
    def __init__(self, center_lat, center_lng, scale=100000):
        self.center_lat = center_lat
        self.center_lng = center_lng
        self.scale = scale  # 经纬度转米/屏幕单位的比例

    def latlng_to_xy(self, lat, lng):
        """经纬度转平面XY坐标"""
        x = (lng - self.center_lng) * self.scale * np.cos(np.radians(self.center_lat))
        y = (lat - self.center_lat) * self.scale
        return round(x, 2), round(y, 2)

    def xy_to_latlng(self, x, y):
        """平面XY坐标转回经纬度"""
        lng = x / (self.scale * np.cos(np.radians(self.center_lat))) + self.center_lng
        lat = y / self.scale + self.center_lat
        return round(lat, 6), round(lng, 6)

# -------------------------- 心跳模拟器（原功能保留）--------------------------
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

# -------------------------- 地图与障碍物生成 --------------------------
def generate_obstacles(lat_min, lat_max, lng_min, lng_max, count=8):
    """在指定范围内生成随机障碍物"""
    obstacles = []
    for i in range(count):
        lat = random.uniform(lat_min, lat_max)
        lng = random.uniform(lng_min, lng_max)
        height = random.uniform(5, 25)  # 障碍物高度5-25米
        obstacles.append({
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "height": round(height, 1),
            "name": f"障碍物 {i+1}"
        })
    return obstacles

def show_3d_map(point_a, point_b, obstacles):
    """显示3D地图：A点、B点、航线、障碍物"""
    # 地图视角
    view_state = pdk.ViewState(
        latitude=(point_a["lat"] + point_b["lat"])/2,
        longitude=(point_a["lng"] + point_b["lng"])/2,
        zoom=16, pitch=45, bearing=0
    )

    # A点图层
    a_layer = pdk.Layer(
        "ScatterplotLayer", data=[point_a],
        get_position=["lng", "lat"], get_color=[0, 255, 0], get_radius=10,
        pickable=True
    )

    # B点图层
    b_layer = pdk.Layer(
        "ScatterplotLayer", data=[point_b],
        get_position=["lng", "lat"], get_color=[255, 0, 0], get_radius=10,
        pickable=True
    )

    # 航线路径
    path = [[point_a["lng"], point_a["lat"]], [point_b["lng"], point_b["lat"]]]
    path_layer = pdk.Layer(
        "LineLayer", data=[{"path": path}],
        get_source_position="path[0]", get_target_position="path[1]",
        get_color=[255, 255, 0], get_width=2
    )

    # 障碍物图层（3D立方体）
    obstacle_layer = pdk.Layer(
        "ColumnLayer", data=obstacles,
        get_position=["lng", "lat"], get_elevation="height",
        elevation_scale=1, radius=8,
        get_fill_color=[255, 165, 0], pickable=True
    )

    # 渲染地图
    r = pdk.Deck(
        layers=[a_layer, b_layer, path_layer, obstacle_layer],
        initial_view_state=view_state,
        tooltip={"text": "{name}\n高度: {height}m"}
    )
    st.pydeck_chart(r)

# -------------------------- 主程序（多页面）--------------------------
def main():
    st.set_page_config(page_title="无人机监控系统", layout="wide")
    # 多页面切换
    page = st.sidebar.radio("功能页面", ["航线规划", "飞行监控"])

    # 南京科技职业学院 坐标范围（真实地图）
    SCHOOL_CENTER_LAT = 32.1805
    SCHOOL_CENTER_LNG = 118.6278
    LAT_MIN, LAT_MAX = 32.178, 32.183
    LNG_MIN, LNG_MAX = 118.625, 118.631

    # 坐标转换工具
    coord_tool = CoordinateTransformer(SCHOOL_CENTER_LAT, SCHOOL_CENTER_LNG)

    # 初始化会话状态
    if "simulator" not in st.session_state:
        st.session_state.simulator = HeartbeatSimulator()
    if "obstacles" not in st.session_state:
        st.session_state.obstacles = generate_obstacles(LAT_MIN, LAT_MAX, LNG_MIN, LNG_MAX)

    # ==================== 页面1：航线规划 ====================
    if page == "航线规划":
        st.title("🛰️ 无人机航线规划（3D地图）")
        st.info("📍 学校：南京科技职业学院 | 坐标系：WGS84")

        # 输入A、B点经纬度
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("A点（起飞点）")
            a_lat = st.number_input("A点纬度", LAT_MIN, LAT_MAX, 32.1805, format="%.6f")
            a_lng = st.number_input("A点经度", LNG_MIN, LNG_MAX, 118.6278, format="%.6f")
        with col2:
            st.subheader("B点（目标点）")
            b_lat = st.number_input("B点纬度", LAT_MIN, LAT_MAX, 32.1810, format="%.6f")
            b_lng = st.number_input("B点经度", LNG_MIN, LNG_MAX, 118.6290, format="%.6f")

        point_a = {"lat": a_lat, "lng": a_lng, "name": "A点"}
        point_b = {"lat": b_lat, "lng": b_lng, "name": "B点"}

        # 坐标转换显示
        a_xy = coord_tool.latlng_to_xy(a_lat, a_lng)
        b_xy = coord_tool.latlng_to_xy(b_lat, b_lng)
        st.markdown(f"**A点平面坐标**：X={a_xy[0]}, Y={a_xy[1]}")
        st.markdown(f"**B点平面坐标**：X={b_xy[0]}, Y={b_xy[1]}")

        # 刷新障碍物
        if st.button("🔄 重新生成障碍物"):
            st.session_state.obstacles = generate_obstacles(LAT_MIN, LAT_MAX, LNG_MIN, LNG_MAX)

        # 显示3D地图
        st.subheader("3D校园地图")
        show_3d_map(point_a, point_b, st.session_state.obstacles)

        # 障碍物列表
        st.subheader("障碍物数据")
        st.dataframe(pd.DataFrame(st.session_state.obstacles), use_container_width=True)

    # ==================== 页面2：飞行监控（心跳包） ====================
    elif page == "飞行监控":
        st.title("✈️ 无人机心跳监控系统")
        simulator = st.session_state.simulator

        # 控制面板
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

        # 地面站控制
        st.sidebar.header("地面站控制")
        simulator.ground_station_online = st.sidebar.checkbox("地面站在线", value=True)
        if not simulator.ground_station_online:
            st.sidebar.warning("地面站离线，模拟信号丢失")

        # 实时显示
        status_placeholder = st.empty()
        chart_placeholder = st.empty()

        while simulator.running:
            latest = simulator.heartbeat_data[-1] if simulator.heartbeat_data else {}
            status_text = f"状态：{latest.get('status','待启动')} | 时间：{latest.get('timestamp','')}"
            status_placeholder.markdown(f"**{status_text}**")

            if simulator.status_data:
                df = pd.DataFrame(simulator.status_data[-50:])
                df['time'] = pd.to_datetime(df['time'])
                chart_placeholder.line_chart(df.set_index('time')['value'], height=300)

            time.sleep(0.1)

        # 停止后显示完整日志
        if simulator.heartbeat_data:
            st.subheader("心跳日志")
            st.dataframe(pd.DataFrame(simulator.heartbeat_data), use_container_width=True)

if __name__ == "__main__":
    main()
