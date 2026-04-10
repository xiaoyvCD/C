import time
import threading
import pandas as pd
import streamlit as st
import random
from datetime import datetime
import numpy as np
import folium
from streamlit_folium import st_folium
import requests
from folium.plugins import Draw, MeasureControl, Fullscreen

# -------------------------- 坐标工具类 --------------------------
class CoordinateTransformer:
    """WGS84经纬度与平面坐标转换工具"""
    def __init__(self, center_lat, center_lng, scale=100000):
        self.center_lat = center_lat
        self.center_lng = center_lng
        self.scale = scale

    def latlng_to_xy(self, lat, lng):
        x = (lng - self.center_lng) * self.scale * np.cos(np.radians(self.center_lat))
        y = (lat - self.center_lat) * self.scale
        return round(x, 2), round(y, 2)

    def xy_to_latlng(self, x, y):
        lng = x / (self.scale * np.cos(np.radians(self.center_lat))) + self.center_lng
        lat = y / self.scale + self.center_lat
        return round(lat, 6), round(lng, 6)

# -------------------------- 心跳模拟器 --------------------------
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

# -------------------------- 稳定版地图组件 --------------------------
def render_folium_map(center_lat=32.1805, center_lng=118.6278, height=600):
    """使用多个瓦片源渲染地图，确保稳定加载"""
    
    # 初始化会话状态
    if "waypoints" not in st.session_state:
        st.session_state.waypoints = []
    if "obstacles" not in st.session_state:
        st.session_state.obstacles = []
    if "map_mode" not in st.session_state:
        st.session_state.map_mode = "航点"
    
    st.info(f"当前模式: {st.session_state.map_mode} | 航点数: {len(st.session_state.waypoints)} | 障碍物: {len(st.session_state.obstacles)}")
    
    try:
        # 创建地图 - 使用多个瓦片源
        m = folium.Map(
            location=[center_lat, center_lng],
            zoom_start=16,
            tiles=None,
            control_scale=True
        )
        
        # 添加多个瓦片层作为备选
        tile_layers = {
            "OpenStreetMap": folium.TileLayer(
                tiles="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                attr="OpenStreetMap",
                name="OpenStreetMap",
                control=True
            ),
            "高德地图": folium.TileLayer(
                tiles="https://webrd01.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}",
                attr="高德地图",
                name="高德地图",
                control=True
            ),
            "CartoDB": folium.TileLayer(
                tiles="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
                attr="CartoDB",
                name="CartoDB",
                control=True
            ),
            "卫星图": folium.TileLayer(
                tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                attr="Esri",
                name="卫星图",
                control=True
            )
        }
        
        # 默认激活 OpenStreetMap
        tile_layers["OpenStreetMap"].add_to(m)
        tile_layers["高德地图"].add_to(m)
        tile_layers["CartoDB"].add_to(m)
        tile_layers["卫星图"].add_to(m)
        
        # 绘制航点
        for i, wp in enumerate(st.session_state.waypoints):
            color = "green" if i == 0 else ("blue" if i == len(st.session_state.waypoints)-1 else "red")
            icon = "play" if i == 0 else ("stop" if i == len(st.session_state.waypoints)-1 else "info-sign")
            
            folium.Marker(
                [wp["lat"], wp["lng"]],
                popup=f"航点 {i+1}<br>纬度: {wp['lat']:.6f}<br>经度: {wp['lng']:.6f}",
                icon=folium.Icon(color=color, icon=icon),
                tooltip=f"航点 {i+1}"
            ).add_to(m)
        
        # 绘制航线
        if len(st.session_state.waypoints) >= 2:
            points = [[wp["lat"], wp["lng"]] for wp in st.session_state.waypoints]
            folium.PolyLine(
                points,
                color="#FF4444",
                weight=3,
                opacity=0.8,
                tooltip=f"航线长度: {calculate_distance(points):.2f} km"
            ).add_to(m)
        
        # 绘制障碍物
        for obs in st.session_state.obstacles:
            folium.Circle(
                location=[obs["lat"], obs["lng"]],
                radius=obs.get("radius", 15),
                color="#FF8C00",
                fill=True,
                fill_color="#FFA500",
                fill_opacity=0.3,
                weight=2,
                popup=f"{obs.get('name', '障碍物')}<br>半径: {obs.get('radius', 15)}m<br>高度: {obs.get('height', 10)}m",
                tooltip=obs.get('name', '障碍物')
            ).add_to(m)
            
            # 添加标签
            folium.Marker(
                [obs["lat"], obs["lng"]],
                icon=folium.DivIcon(
                    html=f'<div style="font-size:10px; color:#FF8C00; font-weight:bold; background:rgba(255,255,255,0.7); padding:2px 4px; border-radius:3px;">{obs.get("name", "")}</div>'
                )
            ).add_to(m)
        
        # 添加点击功能
        m.add_child(folium.LatLngPopup())
        
        # 添加控件
        Fullscreen().add_to(m)
        MeasureControl().add_to(m)
        folium.LayerControl().add_to(m)
        
        # 渲染地图
        map_data = st_folium(m, width='100%', height=height, key="map")
        
        # 处理地图点击
        if map_data and map_data.get("last_clicked"):
            lat = map_data["last_clicked"]["lat"]
            lng = map_data["last_clicked"]["lng"]
            
            if st.session_state.map_mode == "航点":
                if not st.session_state.waypoints or (
                    abs(st.session_state.waypoints[-1]["lat"] - lat) > 0.0001 or 
                    abs(st.session_state.waypoints[-1]["lng"] - lng) > 0.0001
                ):
                    st.session_state.waypoints.append({"lat": lat, "lng": lng})
                    st.success(f"已添加航点: ({lat:.6f}, {lng:.6f})")
                    st.rerun()
            else:
                st.session_state.obstacles.append({
                    "lat": lat,
                    "lng": lng,
                    "radius": 15,
                    "height": 10,
                    "name": f"障碍物{len(st.session_state.obstacles)+1}"
                })
                st.success(f"已添加障碍物: ({lat:.6f}, {lng:.6f})")
                st.rerun()
        
        return map_data
        
    except Exception as e:
        st.error(f"地图加载失败: {str(e)}")
        st.info("请尝试刷新页面或检查网络连接")
        return None

def calculate_distance(points):
    """计算路径总距离（单位：公里）"""
    if len(points) < 2:
        return 0
    
    from math import radians, cos, sin, asin, sqrt
    
    def haversine(lon1, lat1, lon2, lat2):
        lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        r = 6371
        return c * r
    
    total = 0
    for i in range(len(points) - 1):
        total += haversine(
            points[i][1], points[i][0],
            points[i+1][1], points[i+1][0]
        )
    return total

# -------------------------- 获取用户位置 --------------------------
def get_user_location():
    """获取用户大致位置"""
    try:
        response = requests.get('https://ipapi.co/json/', timeout=3)
        if response.status_code == 200:
            data = response.json()
            return {
                'lat': data.get('latitude', 32.1805),
                'lng': data.get('longitude', 118.6278),
                'city': data.get('city', '南京')
            }
    except:
        pass
    return {'lat': 32.1805, 'lng': 118.6278, 'city': '南京'}

# -------------------------- 主程序 --------------------------
def main():
    st.set_page_config(page_title="无人机监控系统", layout="wide")
    st.sidebar.title("🛸 无人机监控系统")
    page = st.sidebar.radio("功能页面", ["🗺️ 航线规划", "❤️ 飞行监控"])
    
    if "simulator" not in st.session_state:
        st.session_state.simulator = HeartbeatSimulator()
    
    # 获取位置
    location = get_user_location()
    st.sidebar.success(f"📍 定位: {location['city']}")
    
    if page == "🗺️ 航线规划":
        st.title("🛰️ 无人机航线规划系统")
        
        # 模式切换
        col1, col2, col3 = st.columns(3)
        with col1:
            mode = st.radio("选择模式", ["航点", "障碍物"], horizontal=True)
            st.session_state.map_mode = mode
        with col2:
            if st.button("🗑️ 清除所有航点", use_container_width=True):
                st.session_state.waypoints = []
                st.rerun()
        with col3:
            if st.button("🧹 清除所有障碍物", use_container_width=True):
                st.session_state.obstacles = []
                st.rerun()
        
        # 手动输入
        with st.expander("📝 手动输入坐标", expanded=False):
            col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
            with col1:
                input_lat = st.number_input("纬度", value=location['lat'], format="%.6f")
            with col2:
                input_lng = st.number_input("经度", value=location['lng'], format="%.6f")
            with col3:
                point_type = st.selectbox("类型", ["航点", "障碍物"])
            with col4:
                if st.button("➕ 添加", use_container_width=True):
                    if point_type == "航点":
                        st.session_state.waypoints.append({"lat": input_lat, "lng": input_lng})
                    else:
                        st.session_state.obstacles.append({
                            "lat": input_lat,
                            "lng": input_lng,
                            "radius": 15,
                            "height": 10,
                            "name": f"障碍物{len(st.session_state.obstacles)+1}"
                        })
                    st.rerun()
        
        # 显示地图
        st.info("💡 提示：如果地图显示空白，请尝试点击右上角的图层按钮切换地图源")
        render_folium_map(
            center_lat=location['lat'],
            center_lng=location['lng'],
            height=600
        )
        
        # 显示数据
        if st.session_state.waypoints:
            st.subheader(f"📍 航点列表 ({len(st.session_state.waypoints)} 个)")
            df_waypoints = pd.DataFrame(st.session_state.waypoints)
            st.dataframe(df_waypoints, use_container_width=True)
            
            if len(st.session_state.waypoints) >= 2:
                points = [[wp["lat"], wp["lng"]] for wp in st.session_state.waypoints]
                distance = calculate_distance(points)
                st.info(f"📏 航线总长度: {distance:.2f} 公里")
        
        if st.session_state.obstacles:
            st.subheader(f"🚧 障碍物列表 ({len(st.session_state.obstacles)} 个)")
            df_obstacles = pd.DataFrame(st.session_state.obstacles)
            st.dataframe(df_obstacles, use_container_width=True)
    
    elif page == "❤️ 飞行监控":
        st.title("✈️ 无人机心跳监控系统")
        simulator = st.session_state.simulator
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("▶️ 启动模拟", use_container_width=True):
                if not simulator.running:
                    simulator.running = True
                    threading.Thread(target=simulator.send_heartbeat, daemon=True).start()
                    threading.Thread(target=simulator.check_timeout, daemon=True).start()
                    st.success("模拟已启动")
        with col2:
            if st.button("⏹️ 停止模拟", use_container_width=True):
                simulator.running = False
                st.warning("模拟已停止")
        
        st.sidebar.checkbox("地面站在线", value=True, key="ground_station")
        simulator.ground_station_online = st.session_state.ground_station
        
        status_placeholder = st.empty()
        chart_placeholder = st.empty()
        
        if simulator.running:
            latest = simulator.heartbeat_data[-1] if simulator.heartbeat_data else {}
            status_placeholder.markdown(f"**状态：{latest.get('status', '运行中')}**")
            
            if simulator.status_data:
                df = pd.DataFrame(simulator.status_data[-50:])
                if not df.empty:
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
