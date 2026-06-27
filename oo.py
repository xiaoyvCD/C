import streamlit as st
import pandas as pd
import os
import json
import numpy as np
import math
import altair as alt
from datetime import datetime, timedelta
import random
import time
import requests
from streamlit_autorefresh import st_autorefresh
import folium
from folium.plugins import Draw
from folium.features import LatLngPopup
from streamlit_folium import st_folium
from streamlit_geolocation import streamlit_geolocation
from shapely.geometry import Polygon, Point, LineString

st.set_page_config(page_title="无人机心跳+航线规划+通信链路", page_icon="🚁", layout="wide")

# -------------------- 基础工具 --------------------
PI = math.pi

# ==================== WGS-84 ↔ GCJ-02 坐标转换 ====================
def wgs84_to_gcj02(lat, lon):
    """
    WGS-84 转 GCJ-02 (火星坐标系)
    适用于：高德地图、腾讯地图等国内地图服务
    """
    a = 6378245.0
    ee = 0.00669342162296594323

    dlat = _transform_lat(lat - 35.0, lon - 105.0)
    dlon = _transform_lon(lat - 35.0, lon - 105.0)

    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)

    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlon = (dlon * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)

    mg_lat = lat + dlat
    mg_lon = lon + dlon
    return mg_lat, mg_lon

def gcj02_to_wgs84(lat, lon):
    """
    GCJ-02 转 WGS-84 (近似逆转换)
    适用于：将高德坐标转回GPS坐标
    """
    a = 6378245.0
    ee = 0.00669342162296594323

    dlat = _transform_lat(lat - 35.0, lon - 105.0)
    dlon = _transform_lon(lat - 35.0, lon - 105.0)

    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)

    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlon = (dlon * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)

    mg_lat = lat + dlat
    mg_lon = lon + dlon
    return lat * 2 - mg_lat, lon * 2 - mg_lon

def _transform_lat(x, y):
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret

def _transform_lon(x, y):
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret

def wgs84_to_bd09(lat, lon):
    """
    WGS-84 转 BD-09 (百度坐标系)
    两步转换：WGS-84 → GCJ-02 → BD-09
    """
    gcj_lat, gcj_lon = wgs84_to_gcj02(lat, lon)
    # GCJ-02 转 BD-09
    z = math.sqrt(gcj_lon * gcj_lon + gcj_lat * gcj_lat) + 0.00002 * math.sin(gcj_lat * math.pi * 3000.0 / 180.0)
    theta = math.atan2(gcj_lat, gcj_lon) + 0.000003 * math.cos(gcj_lon * math.pi * 3000.0 / 180.0)
    bd_lon = z * math.cos(theta) + 0.0065
    bd_lat = z * math.sin(theta) + 0.006
    return bd_lat, bd_lon

def gcj02_to_bd09(lat, lon):
    """GCJ-02 转 BD-09"""
    z = math.sqrt(lon * lon + lat * lat) + 0.00002 * math.sin(lat * math.pi * 3000.0 / 180.0)
    theta = math.atan2(lat, lon) + 0.000003 * math.cos(lon * math.pi * 3000.0 / 180.0)
    bd_lon = z * math.cos(theta) + 0.0065
    bd_lat = z * math.sin(theta) + 0.006
    return bd_lat, bd_lon

def bd09_to_gcj02(lat, lon):
    """BD-09 转 GCJ-02"""
    x = lon - 0.0065
    y = lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * math.pi * 3000.0 / 180.0)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * math.pi * 3000.0 / 180.0)
    gcj_lon = z * math.cos(theta)
    gcj_lat = z * math.sin(theta)
    return gcj_lat, gcj_lon

def bd09_to_wgs84(lat, lon):
    """BD-09 转 WGS-84"""
    gcj_lat, gcj_lon = bd09_to_gcj02(lat, lon)
    return gcj02_to_wgs84(gcj_lat, gcj_lon)

# ==================== 原有工具函数 ====================
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def bearing(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1)*math.sin(phi2) - math.sin(phi1)*math.cos(phi2)*math.cos(dlambda)
    brng = math.atan2(y, x)
    return (math.degrees(brng) + 360) % 360

def point_in_polygon(point, poly):
    lat, lon = point
    return Polygon([(p[1], p[0]) for p in poly]).contains(Point(lon, lat))

def line_intersects_polygon(p1, p2, poly):
    line = LineString([(p1[1], p1[0]), (p2[1], p2[0])])
    polygon = Polygon([(p[1], p[0]) for p in poly])
    return line.intersects(polygon)

def expand_polygon(poly, distance_m):
    polygon_shp = Polygon([(p[1], p[0]) for p in poly])
    buffer_deg = distance_m / 111320.0
    expanded = polygon_shp.buffer(buffer_deg, resolution=16)
    if expanded.geom_type == 'Polygon':
        coords = list(expanded.exterior.coords)
        return [[lat, lon] for lon, lat in coords]
    else:
        largest = max(expanded.geoms, key=lambda g: g.area)
        coords = list(largest.exterior.coords)
        return [[lat, lon] for lon, lat in coords]

# -------------------- 改进的绕行逻辑 --------------------
def detour_path_around_polygon(start, end, poly, safety_dist=5):
    expanded_poly = expand_polygon(poly, safety_dist)
    n = len(expanded_poly)
    min_start, min_end = float('inf'), float('inf')
    idx_start, idx_end = 0, 0
    for i, p in enumerate(expanded_poly):
        d = haversine(start[0], start[1], p[0], p[1])
        if d < min_start:
            min_start = d; idx_start = i
        d = haversine(end[0], end[1], p[0], p[1])
        if d < min_end:
            min_end = d; idx_end = i

    def clockwise_path(a, b):
        if a <= b:
            return list(range(a, b+1))
        else:
            return list(range(a, n)) + list(range(0, b+1))

    def counterclockwise_path(a, b):
        if a >= b:
            return list(range(a, b-1, -1))
        else:
            return list(range(a, -1, -1)) + list(range(n-1, b-1, -1))

    path1_idx = clockwise_path(idx_start, idx_end)
    path2_idx = counterclockwise_path(idx_start, idx_end)

    def path_len(idx_list):
        total = 0
        for i in range(len(idx_list)-1):
            p1 = expanded_poly[idx_list[i]]
            p2 = expanded_poly[idx_list[i+1]]
            total += haversine(p1[0], p1[1], p2[0], p2[1])
        total += haversine(start[0], start[1], expanded_poly[idx_list[0]][0], expanded_poly[idx_list[0]][1])
        total += haversine(expanded_poly[idx_list[-1]][0], expanded_poly[idx_list[-1]][1], end[0], end[1])
        return total

    shorter = path1_idx if path_len(path1_idx) <= path_len(path2_idx) else path2_idx
    waypoints = [start]
    for idx in shorter:
        waypoints.append(expanded_poly[idx])
    waypoints.append(end)
    return waypoints

def detour_path_multi(start, end, obstacles, safety_dist=5, max_iter=10):
    current_segment = [start, end]
    for _ in range(max_iter):
        new_segment = []
        segment_changed = False
        for i in range(len(current_segment)-1):
            p1 = current_segment[i]
            p2 = current_segment[i+1]
            intersected = False
            for obs in obstacles:
                if obs.get("type") == "no-fly" or obs.get("height", 0) >= st.session_state.get("fly_height", 50):
                    if line_intersects_polygon(p1, p2, obs["polygon"]):
                        detour = detour_path_around_polygon(p1, p2, obs["polygon"], safety_dist)
                        new_segment.extend(detour[:-1])
                        intersected = True
                        segment_changed = True
                        break
            if not intersected:
                new_segment.append(p1)
        new_segment.append(current_segment[-1])
        current_segment = new_segment
        if not segment_changed:
            break
    cleaned = [current_segment[0]]
    for p in current_segment[1:]:
        if p != cleaned[-1]:
            cleaned.append(p)
    return cleaned

def plan_path(route, obstacles, fly_height, safety_dist=5):
    if len(route) < 2:
        return route
    final_path = []
    for i in range(len(route)-1):
        p1, p2 = route[i], route[i+1]
        for obs in obstacles:
            if obs.get("type") == "no-fly" and (point_in_polygon(p1, obs["polygon"]) or point_in_polygon(p2, obs["polygon"])):
                st.error(f"航点位于禁飞区内，无法规划路径！")
                return []
        segment = detour_path_multi(p1, p2, obstacles, safety_dist)
        if final_path:
            if segment[0] == final_path[-1]:
                final_path.extend(segment[1:])
            else:
                final_path.extend(segment)
        else:
            final_path.extend(segment)
    unique = [final_path[0]]
    for p in final_path[1:]:
        if p != unique[-1]:
            unique.append(p)
    return unique

# -------------------- 持久化 --------------------
OBSTACLE_FILE = "obstacles.json"
def load_obstacles():
    if os.path.exists(OBSTACLE_FILE):
        with open(OBSTACLE_FILE, "r") as f:
            return json.load(f)
    return []
def save_obstacles(obs):
    with open(OBSTACLE_FILE, "w") as f:
        json.dump(obs, f, indent=2)

# -------------------- 心跳模拟 --------------------
def generate_heartbeats(start_time, disconnected, disconnect_time=None, stopped=False, stop_time=None):
    now = datetime.now()
    end_time = stop_time if stopped and stop_time is not None else now
    elapsed = (end_time - start_time).total_seconds()
    if elapsed < 0:
        return pd.DataFrame(), False
    n_beats = int(elapsed) + 1
    data = []
    last_recv_time = None
    timeout_occurred = False
    for i in range(1, n_beats + 1):
        send_time = start_time + timedelta(seconds=i-1)
        is_disconnected = disconnected and disconnect_time and send_time >= disconnect_time
        success = False if is_disconnected else random.random() < 0.9
        recv_time = send_time if success else None
        status = "成功" if success else "丢失"
        if success:
            last_recv_time = recv_time
        if last_recv_time and (send_time - last_recv_time).total_seconds() > 3:
            status = "超时"
            timeout_occurred = True
            last_recv_time = send_time
        data.append({"序号": i, "发送时间": send_time.strftime("%Y-%m-%d %H:%M:%S"),
                     "接收时间": recv_time.strftime("%Y-%m-%d %H:%M:%S") if recv_time else None,
                     "状态": status})
        if timeout_occurred and not is_disconnected:
            return pd.DataFrame(data), True
    return pd.DataFrame(data), False

# -------------------- 高精度定位 & 逆地理编码 (已支持GCJ-02) --------------------
def reverse_geocode_amap(lat, lon, key):
    """
    调用高德逆地理编码API，返回详细地址
    注意：高德 API 要求输入 GCJ-02 坐标，调用前请先转换！
    """
    if not key or key.strip() == "":
        return None
    url = f"https://restapi.amap.com/v3/geocode/regeo?output=json&location={lon},{lat}&key={key}&radius=100&extensions=all"
    try:
        resp = requests.get(url, timeout=5)
        data = resp.json()
        if data.get("status") == "1" and data.get("regeocode"):
            formatted = data["regeocode"].get("formatted_address", "")
            building = data["regeocode"].get("addressComponent", {}).get("building", {})
            if building and building.get("name"):
                return f"{formatted} {building['name']}"
            return formatted
    except:
        pass
    return None

# -------------------- 通信链路模拟 (GCS-OBC-FCU) --------------------
def init_link_simulator():
    if "link_sim" not in st.session_state:
        st.session_state.link_sim = {
            "gcs_obc": {
                "connected": True,
                "base_delay": 15,
                "jitter": 5,
                "loss_rate": 0.02,
                "total_packets": 0,
                "lost_packets": 0,
                "current_delay": 0,
            },
            "obc_fcu": {
                "connected": True,
                "base_delay": 25,
                "jitter": 8,
                "loss_rate": 0.03,
                "total_packets": 0,
                "lost_packets": 0,
                "current_delay": 0,
            },
            "logs": [],
            "last_update": datetime.now(),
        }
    if len(st.session_state.link_sim["logs"]) > 200:
        st.session_state.link_sim["logs"] = st.session_state.link_sim["logs"][-200:]

def update_link_simulator():
    sim = st.session_state.link_sim
    now = datetime.now()
    if (now - sim["last_update"]).total_seconds() < 0.5:
        return
    sim["last_update"] = now

    for link_name in ["gcs_obc", "obc_fcu"]:
        link = sim[link_name]
        if link["connected"]:
            delay = np.random.normal(link["base_delay"], link["jitter"]/2)
            link["current_delay"] = max(0, round(delay, 1))
            if random.random() < link["loss_rate"]:
                link["lost_packets"] += 1
            link["total_packets"] += 1
        else:
            link["current_delay"] = None
            link["lost_packets"] += 1
            link["total_packets"] += 1

        if link["total_packets"] > 0:
            link["current_loss"] = round(link["lost_packets"] / link["total_packets"] * 100, 1)
            if link["total_packets"] > 100:
                link["lost_packets"] = max(0, link["lost_packets"] - 1)
                link["total_packets"] = max(1, link["total_packets"] - 1)

    if sim["gcs_obc"]["connected"] and sim["obc_fcu"]["connected"]:
        if random.random() < 0.3:
            msg_gcs = f"CMD_SET_WAYPOINT seq={random.randint(1,100)}"
            sim["logs"].append((now.strftime("%H:%M:%S"), "GCS→OBC", msg_gcs))
            sim["logs"].append((now.strftime("%H:%M:%S"), "OBC→FCU (NAVLink)", f"转发: {msg_gcs}"))
            msg_fcu = f"ACK seq={random.randint(1,100)}"
            sim["logs"].append((now.strftime("%H:%M:%S"), "FCU→OBC", msg_fcu))
            sim["logs"].append((now.strftime("%H:%M:%S"), "OBC→GCS (UDP)", f"转发: {msg_fcu}"))
        elif random.random() < 0.2:
            tele = f"TELEMETRY: bat={random.randint(70,100)}%, h={random.randint(10,200)}m"
            sim["logs"].append((now.strftime("%H:%M:%S"), "GCS→OBC", "REQUEST_TELEMETRY"))
            sim["logs"].append((now.strftime("%H:%M:%S"), "OBC→FCU", "GET_STATUS"))
            sim["logs"].append((now.strftime("%H:%M:%S"), "FCU→OBC", tele))
            sim["logs"].append((now.strftime("%H:%M:%S"), "OBC→GCS", tele))
    elif sim["gcs_obc"]["connected"] and not sim["obc_fcu"]["connected"]:
        sim["logs"].append((now.strftime("%H:%M:%S"), "OBC→GCS", "警告: OBC-FCU链路断开"))
    elif not sim["gcs_obc"]["connected"]:
        sim["logs"].append((now.strftime("%H:%M:%S"), "系统", "GCS-OBC链路断开，无法通信"))

    if len(sim["logs"]) > 100:
        sim["logs"] = sim["logs"][-100:]

# -------------------- 页面布局 --------------------
tab1, tab2, tab3 = st.tabs(["🗺️ 航线规划与模拟", "📡 飞行监控", "🔗 通信链路拓扑与数据流"])

# ==================== 标签1 ====================
with tab1:
    st.title("🗺️ 无人机航线规划与智能绕飞")
    st.markdown("双视图 | 拖拽航点 | 禁飞区强制绕行 | 5米安全距离 | 沿边界最短绕飞 | 实时飞行监控")

    # ---------- 初始化 session ----------
    defaults = {
        "waypoints": [],
        "obstacles": load_obstacles(),
        "fly_height": 50.0,
        "fly_speed": 10.0,
        "drone_battery": 100.0,
        "drone_bat_temp": 32.0,
        "outside_temp": 28.0,
        "sim_path_outbound": [],
        "sim_path_return": [],
        "sim_mode": "outbound",
        "sim_pos": 0,
        "drawing_type": "普通障碍物",
        "trash": [],
        "center_lat": 32.030,
        "center_lon": 118.787,
        "show_route_labels": False,
        "takeoff_idx": 0,
        "land_idx": None,
        "map_key_counter": 0,
        "move_wp_index": None,
        "flight_status": "idle",
        "flight_start_time": None,
        "flight_paused_time": None,
        "flight_accumulated_time": 0.0,
        "flight_initial_battery": 100.0,
        "battery_per_meter": 0.005,
        "sim_route_outbound": [],
        "sim_route_return": [],
        "precise_address": "",
        "map_style": "标准街道",
        "operation_mode": "✈️ 航线规划",
        # 坐标系转换相关
        "coord_system": "WGS-84",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # 校准起降索引
    n_wp = len(st.session_state.waypoints)
    if n_wp == 0:
        st.session_state.takeoff_idx = 0
        st.session_state.land_idx = None
    else:
        st.session_state.takeoff_idx = min(max(st.session_state.takeoff_idx, 0), n_wp - 1)
        if st.session_state.land_idx is None or st.session_state.land_idx >= n_wp:
            st.session_state.land_idx = n_wp - 1
        st.session_state.land_idx = min(max(st.session_state.land_idx, 0), n_wp - 1)

    # ---------- 侧边栏 ----------
    with st.sidebar:
        st.header("📍 精确定位（自动获取）")
        location = streamlit_geolocation()
        if location and location.get('latitude'):
            lat = location['latitude']
            lon = location['longitude']

            # WGS-84 转 GCJ-02（用于高德逆地理编码）
            gcj_lat, gcj_lon = wgs84_to_gcj02(lat, lon)

            if abs(st.session_state.center_lat - lat) > 1e-6 or abs(st.session_state.center_lon - lon) > 1e-6:
                st.session_state.center_lat = lat
                st.session_state.center_lon = lon
                amap_key = st.text_input("高德逆地理编码Key（可选）", type="password", key="amap_key_input")
                if amap_key:
                    # 使用 GCJ-02 坐标调用高德 API
                    addr = reverse_geocode_amap(gcj_lat, gcj_lon, amap_key)
                    st.session_state.precise_address = addr if addr else f"坐标 ({lat:.5f}, {lon:.5f})"
                else:
                    st.session_state.precise_address = f"坐标 ({lat:.5f}, {lon:.5f})"
                st.success(f"已自动定位至: {st.session_state.precise_address}")
        st.write(f"📍 当前定位: {st.session_state.get('precise_address', '未获取')}")

        # 坐标系选择
        st.divider()
        st.header("🗺️ 坐标系设置")
        st.session_state.coord_system = st.radio(
            "显示坐标类型",
            ["WGS-84 (GPS)", "GCJ-02 (火星)", "BD-09 (百度)"],
            horizontal=True,
            key="coord_system_radio"
        )

        c1, c2 = st.columns(2)
        with c1:
            st.session_state.center_lat = st.number_input("纬度", value=st.session_state.center_lat, format="%.6f", key="center_lat_input")
        with c2:
            st.session_state.center_lon = st.number_input("经度", value=st.session_state.center_lon, format="%.6f", key="center_lon_input")

        st.divider()
        st.header("🗺️ 地图样式")
        st.session_state.map_style = st.radio("选择底图", ["卫星实景", "标准街道"], horizontal=True, key="map_style_radio")

        st.divider()
        st.header("🎛️ 飞行参数")
        col_h1, col_h2 = st.columns([3,1])
        with col_h1:
            fly_h = st.slider("高度(m)", 10, 200, int(st.session_state.fly_height))
        with col_h2:
            fly_h_in = st.number_input("自定义", 10, 200, int(st.session_state.fly_height), step=1, key="fly_height_custom")
        st.session_state.fly_height = float(fly_h_in if fly_h_in != st.session_state.fly_height else fly_h)

        col_s1, col_s2 = st.columns([3,1])
        with col_s1:
            fly_s = st.slider("速度(m/s)", 1, 30, int(st.session_state.fly_speed))
        with col_s2:
            fly_s_in = st.number_input("自定义", 1, 30, int(st.session_state.fly_speed), step=1, key="fly_speed_custom")
        st.session_state.fly_speed = float(fly_s_in if fly_s_in != st.session_state.fly_speed else fly_s)

        st.divider()
        st.header("📊 状态")
        st.metric("高度", f"{st.session_state.fly_height} m")
        st.metric("速度", f"{st.session_state.fly_speed} m/s")
        st.metric("电量", f"{st.session_state.drone_battery}%")
        st.metric("电池温度", f"{st.session_state.drone_bat_temp}°C")
        st.metric("室外温度", f"{st.session_state.outside_temp}°C")

        st.divider()
        st.header("🗂️ 操作模式")
        st.session_state.operation_mode = st.radio("模式", ["✈️ 航线规划", "🧱 障碍物绘制"], index=0, key="op_mode")
        if st.session_state.move_wp_index is not None:
            st.info(f"正在移动航点 #{st.session_state.move_wp_index+1}，点击地图新位置")
            if st.button("取消移动"):
                st.session_state.move_wp_index = None
                st.rerun()

        st.divider()
        st.header("✈️ 航线控制")
        show_labels = st.checkbox("显示航线标记", value=st.session_state.show_route_labels)
        st.session_state.show_route_labels = show_labels
        if st.button("清空航点", use_container_width=True):
            st.session_state.waypoints = []
            st.session_state.land_idx = None
            st.session_state.takeoff_idx = 0
            st.session_state.sim_path_outbound = []
            st.session_state.sim_path_return = []
            st.session_state.sim_route_outbound = []
            st.session_state.sim_route_return = []
            st.session_state.sim_pos = 0
            st.session_state.flight_status = "idle"
            st.rerun()

        st.caption(f"当前航点数: {n_wp}")

        if n_wp > 0:
            c3, c4 = st.columns(2)
            with c3:
                st.session_state.takeoff_idx = st.number_input("起飞点", min_value=0, max_value=n_wp-1,
                                                               value=st.session_state.takeoff_idx, step=1, key="takeoff_idx_input")
            with c4:
                land_val = st.session_state.land_idx if st.session_state.land_idx is not None else n_wp - 1
                st.session_state.land_idx = st.number_input("降落点", min_value=0, max_value=n_wp-1,
                                                            value=land_val, step=1, key="land_idx_input")
            st.caption(f"🟢 起飞点: #{st.session_state.takeoff_idx+1}  🔴 降落点: #{st.session_state.land_idx+1}")

        st.divider()
        st.header("🧱 障碍物管理")
        st.session_state.drawing_type = st.radio("绘制类型", ["普通障碍物", "禁飞区"], key="draw_type")
        for i, obs in enumerate(st.session_state.obstacles):
            with st.expander(f"#{i} {obs.get('type','normal')} (高{obs.get('height',30)}m)", expanded=False):
                c_h, c_focus = st.columns([3,1])
                with c_h:
                    new_h = st.number_input(f"高度(m)", min_value=1, max_value=500, value=obs["height"], step=5, key=f"obs_h_{i}")
                    if new_h != obs["height"]:
                        st.session_state.obstacles[i]["height"] = new_h
                        save_obstacles(st.session_state.obstacles)
                with c_focus:
                    if st.button("📍", key=f"focus_{i}"):
                        lats = [p[0] for p in obs["polygon"]]
                        lons = [p[1] for p in obs["polygon"]]
                        st.session_state.center_lat = np.mean(lats)
                        st.session_state.center_lon = np.mean(lons)
                        st.rerun()
                if st.button("删除", key=f"del_obs_{i}"):
                    st.session_state.trash.append(st.session_state.obstacles.pop(i))
                    save_obstacles(st.session_state.obstacles)
                    st.rerun()
        if st.button("↩️ 恢复最近删除"):
            if st.session_state.trash:
                st.session_state.obstacles.append(st.session_state.trash.pop())
                save_obstacles(st.session_state.obstacles)
                st.rerun()

    # ---------- 地图绘制 ----------
    map_center = [st.session_state.center_lat, st.session_state.center_lon]

    # 根据选择的坐标系转换显示坐标（用于地图标注）
    coord_system = st.session_state.get("coord_system", "WGS-84 (GPS)")

    if st.session_state.map_style == "卫星实景":
        tiles = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
        attr = "Esri"
    else:
        tiles = "CartoDB positron"
        attr = "CartoDB"

    m = folium.Map(location=map_center, zoom_start=17, tiles=tiles, attr=attr)

    if st.session_state.precise_address:
        folium.Marker(map_center, icon=folium.Icon(color="green", icon="info-sign"),
                      popup=st.session_state.precise_address).add_to(m)
    else:
        folium.Marker(map_center, icon=folium.Icon(color="red", icon="home"), popup="中心点").add_to(m)

    if st.session_state.operation_mode.startswith("🧱"):
        Draw(draw_options={'polyline': False, 'rectangle': True, 'polygon': True,
                           'circle': False, 'marker': False, 'circlemarker': False},
             edit_options={'edit': True}).add_to(m)
    else:
        LatLngPopup().add_to(m)

    for idx, obs in enumerate(st.session_state.obstacles):
        color = "black" if obs.get("type") == "no-fly" else "red"
        folium.Polygon(locations=obs["polygon"], color=color, weight=2, fill=True, fill_opacity=0.2,
                       popup=f"#{idx} {obs.get('type','normal')} 高{obs.get('height',30)}m").add_to(m)

    if n_wp > 0:
        pts = st.session_state.waypoints
        takeoff = st.session_state.takeoff_idx
        land = st.session_state.land_idx if st.session_state.land_idx is not None else n_wp - 1

        if st.session_state.show_route_labels:
            for i, wp in enumerate(pts):
                if i == takeoff:
                    icon = folium.Icon(color="green", icon="play", prefix="fa")
                elif i == land:
                    icon = folium.Icon(color="red", icon="stop", prefix="fa")
                else:
                    icon = folium.DivIcon(html=f'<div style="background:white; border-radius:50%; width:22px; height:22px; text-align:center; line-height:22px; border:2px solid blue">{i+1}</div>')
                folium.Marker(wp, icon=icon).add_to(m)
        folium.PolyLine(pts, color="gray", weight=1, dash_array="5,5").add_to(m)

    if st.session_state.sim_path_outbound:
        folium.PolyLine(st.session_state.sim_path_outbound, color="blue", weight=3).add_to(m)
    if st.session_state.sim_path_return:
        folium.PolyLine(st.session_state.sim_path_return, color="green", weight=3).add_to(m)

    current_path = st.session_state.sim_path_outbound if st.session_state.sim_mode == "outbound" else st.session_state.sim_path_return
    if current_path and st.session_state.sim_pos < len(current_path):
        pos = current_path[st.session_state.sim_pos]
        folium.Marker(pos, icon=folium.DivIcon(html='<i class="fa fa-fighter-jet" style="font-size:24px; color:purple;"></i>'),
                      popup="无人机当前位置").add_to(m)

    map_data = st_folium(m, width=900, height=600, key=f"map_{st.session_state.map_key_counter}")

    # ---------- 事件处理 ----------
    if st.session_state.operation_mode.startswith("🧱") and map_data and map_data.get("last_active_drawing"):
        geo = map_data["last_active_drawing"]
        if geo and "geometry" in geo:
            coords = geo["geometry"]["coordinates"][0]
            poly = [[c[1], c[0]] for c in coords]
            exist = any(np.array_equal(np.array(o["polygon"]), np.array(poly)) for o in st.session_state.obstacles)
            if not exist:
                obs_type = "no-fly" if st.session_state.drawing_type == "禁飞区" else "normal"
                st.session_state.obstacles.append({"polygon": poly, "height": 30, "type": obs_type})
                save_obstacles(st.session_state.obstacles)
                st.rerun()

    if not st.session_state.operation_mode.startswith("🧱") and map_data and map_data.get("last_clicked"):
        lat = map_data["last_clicked"]["lat"]
        lon = map_data["last_clicked"]["lng"]

        # 如果当前坐标系不是 WGS-84，点击坐标需要转换后存储
        if "GCJ" in coord_system:
            # 将 GCJ-02 转回 WGS-84 存储
            lat, lon = gcj02_to_wgs84(lat, lon)
        elif "BD" in coord_system:
            lat, lon = bd09_to_wgs84(lat, lon)

        if st.session_state.move_wp_index is not None:
            idx = st.session_state.move_wp_index
            st.session_state.waypoints[idx] = (lat, lon)
            st.session_state.move_wp_index = None
            st.success(f"航点 #{idx+1} 已移动至新位置")
            st.rerun()
        else:
            st.session_state.waypoints.append((lat, lon))
            st.session_state.land_idx = len(st.session_state.waypoints) - 1
            st.rerun()

    # ---------- 航点详情与移动 ----------
    st.divider()
    st.subheader("📋 航点详情 (点击“移动”后在地图上单击新位置)")
    if n_wp == 0:
        st.info("暂无航点，请在地图上点击添加。")
    else:
        takeoff = st.session_state.takeoff_idx
        land = st.session_state.land_idx if st.session_state.land_idx is not None else n_wp - 1
        st.caption(f"🟢 起飞点: 航点 #{takeoff+1}  |  🔴 降落点: 航点 #{land+1}")

        cols = st.columns([1, 2, 2, 1, 1, 1])
        cols[0].write("**序号**")
        cols[1].write("**纬度**")
        cols[2].write("**经度**")
        cols[3].write("**距离(m)**")
        cols[4].write("**方位角**")
        cols[5].write("**操作**")

        for i, wp in enumerate(st.session_state.waypoints):
            col_idx, col_lat, col_lon, col_dist, col_ang, col_act = st.columns([1,2,2,1,1,1])
            label = f"{i+1}"
            if i == takeoff:
                label = f"🟢 {i+1}"
            elif i == land:
                label = f"🔴 {i+1}"
            col_idx.write(label)

            # 根据选择的坐标系显示航点坐标
            if coord_system == "GCJ-02 (火星)":
                disp_lat, disp_lon = wgs84_to_gcj02(wp[0], wp[1])
            elif coord_system == "BD-09 (百度)":
                disp_lat, disp_lon = wgs84_to_bd09(wp[0], wp[1])
            else:
                disp_lat, disp_lon = wp[0], wp[1]
            col_lat.write(round(disp_lat, 6))
            col_lon.write(round(disp_lon, 6))

            if i > 0:
                prev = st.session_state.waypoints[i-1]
                dist = haversine(prev[0], prev[1], wp[0], wp[1])
                ang = bearing(prev[0], prev[1], wp[0], wp[1])
                col_dist.write(f"{dist:.1f}")
                col_ang.write(f"{ang:.1f}")
            else:
                col_dist.write("-")
                col_ang.write("-")
            if col_act.button("🔄 移动", key=f"move_wp_{i}"):
                st.session_state.move_wp_index = i
                st.rerun()

    # ---------- 路径规划及模拟控制 ----------
    st.divider()
    st.subheader("🚀 路径规划与模拟")
    col_plan1, col_plan2, col_plan3 = st.columns(3)
    with col_plan1:
        if st.button("🛫 规划去程路径", use_container_width=True):
            if n_wp < 2:
                st.warning("至少需要两个航点！")
            else:
                start_i = st.session_state.takeoff_idx
                end_i = st.session_state.land_idx if st.session_state.land_idx is not None else n_wp - 1
                if start_i == end_i and n_wp > 1:
                    end_i = n_wp - 1
                    st.session_state.land_idx = end_i
                if start_i <= end_i:
                    route = st.session_state.waypoints[start_i:end_i+1]
                else:
                    route = st.session_state.waypoints[start_i:] + st.session_state.waypoints[:end_i+1]
                st.session_state.sim_route_outbound = route
                st.session_state.sim_path_outbound = plan_path(route, st.session_state.obstacles, st.session_state.fly_height, safety_dist=5)
                st.session_state.sim_path_return = []
                st.session_state.sim_mode = "outbound"
                st.session_state.sim_pos = 0
                st.session_state.flight_status = "idle"
                if st.session_state.sim_path_outbound:
                    st.success("去程路径已生成（蓝色线）")
                st.rerun()

    with col_plan2:
        if st.button("🛬 规划返程路径", use_container_width=True):
            if n_wp < 2:
                st.warning("至少需要两个航点！")
            else:
                start_i = st.session_state.land_idx if st.session_state.land_idx is not None else n_wp - 1
                end_i = st.session_state.takeoff_idx
                if start_i == end_i and n_wp > 1:
                    start_i = n_wp - 1
                    st.session_state.land_idx = start_i
                if start_i <= end_i:
                    route = st.session_state.waypoints[start_i:end_i+1]
                else:
                    route = st.session_state.waypoints[start_i:] + st.session_state.waypoints[:end_i+1]
                st.session_state.sim_route_return = route
                st.session_state.sim_path_return = plan_path(route, st.session_state.obstacles, st.session_state.fly_height, safety_dist=5)
                st.session_state.sim_mode = "return"
                st.session_state.sim_pos = 0
                st.session_state.flight_status = "idle"
                if st.session_state.sim_path_return:
                    st.success("返程路径已生成（绿色线）")
                st.rerun()

    with col_plan3:
        if st.button("⏹️ 清除路径", use_container_width=True):
            st.session_state.sim_path_outbound = []
            st.session_state.sim_path_return = []
            st.session_state.sim_route_outbound = []
            st.session_state.sim_route_return = []
            st.session_state.sim_pos = 0
            st.session_state.flight_status = "idle"
            st.rerun()

    if st.session_state.sim_path_outbound or st.session_state.sim_path_return:
        st.session_state.sim_mode = st.radio("当前模拟方向", ["outbound", "return"],
                                             format_func=lambda x: "去程 (蓝色)" if x=="outbound" else "返程 (绿色)",
                                             horizontal=True, key="sim_mode_select")

    current_path = st.session_state.sim_path_outbound if st.session_state.sim_mode == "outbound" else st.session_state.sim_path_return
    if current_path:
        max_pos = len(current_path) - 1
        manual_disabled = (st.session_state.flight_status in ["running", "finished"])
        sim_pos = st.slider("手动控制无人机位置", 0, max_pos, st.session_state.sim_pos,
                            key="sim_slider", disabled=manual_disabled)
        if not manual_disabled:
            st.session_state.sim_pos = sim_pos
        st.caption(f"📍 当前无人机坐标: {current_path[st.session_state.sim_pos]}")

    # 自动飞行实时模拟
    st.divider()
    st.subheader("🎮 自动飞行实时模拟")
    if not current_path:
        st.info("请先生成去程或返程路径。")
    else:
        total_distance = sum(haversine(current_path[i][0], current_path[i][1],
                                       current_path[i+1][0], current_path[i+1][1])
                             for i in range(len(current_path)-1))

        if st.session_state.flight_status == "running":
            st_autorefresh(interval=1000, key="flight_autorefresh")

        col_ctrl1, col_ctrl2, col_ctrl3 = st.columns(3)
        with col_ctrl1:
            if st.session_state.flight_status in ["idle", "paused", "finished"]:
                if st.button("▶️ 开始/继续飞行", use_container_width=True):
                    now = datetime.now()
                    if st.session_state.flight_status == "paused":
                        paused_duration = (now - st.session_state.flight_paused_time).total_seconds()
                        st.session_state.flight_accumulated_time += paused_duration
                    else:
                        st.session_state.flight_start_time = now
                        st.session_state.flight_accumulated_time = 0.0
                        st.session_state.sim_pos = 0
                        st.session_state.drone_battery = st.session_state.flight_initial_battery
                    st.session_state.flight_status = "running"
                    st.rerun()
        with col_ctrl2:
            if st.session_state.flight_status == "running":
                if st.button("⏸️ 暂停", use_container_width=True):
                    st.session_state.flight_status = "paused"
                    st.session_state.flight_paused_time = datetime.now()
                    st.rerun()
        with col_ctrl3:
            if st.session_state.flight_status in ["running", "paused"]:
                if st.button("⏹️ 停止", use_container_width=True):
                    st.session_state.flight_status = "idle"
                    st.rerun()

        if st.session_state.flight_status == "running":
            now = datetime.now()
            elapsed_real = (now - st.session_state.flight_start_time).total_seconds()
            flight_time = st.session_state.flight_accumulated_time + elapsed_real
            flown_distance = st.session_state.fly_speed * flight_time

            cum_dist = 0.0
            new_pos = 0
            for i in range(len(current_path)-1):
                seg_len = haversine(current_path[i][0], current_path[i][1],
                                    current_path[i+1][0], current_path[i+1][1])
                if cum_dist + seg_len >= flown_distance:
                    new_pos = i
                    break
                cum_dist += seg_len
            else:
                new_pos = len(current_path)-1
            st.session_state.sim_pos = min(new_pos, len(current_path)-1)

            if flown_distance >= total_distance:
                st.session_state.flight_status = "finished"
                st.session_state.sim_pos = len(current_path)-1
                battery_used = total_distance * st.session_state.battery_per_meter
                st.session_state.drone_battery = max(0.0, st.session_state.flight_initial_battery - battery_used)
                st.rerun()

            battery_used = flown_distance * st.session_state.battery_per_meter
            st.session_state.drone_battery = max(0.0, st.session_state.flight_initial_battery - battery_used)

        current_pos_idx = st.session_state.sim_pos
        precise_flown = 0.0
        if st.session_state.flight_status == "finished":
            precise_flown = total_distance
        else:
            for i in range(current_pos_idx):
                precise_flown += haversine(current_path[i][0], current_path[i][1],
                                           current_path[i+1][0], current_path[i+1][1])
            if st.session_state.flight_status == "running" and current_pos_idx < len(current_path)-1:
                cum_before = 0.0
                for i in range(current_pos_idx):
                    cum_before += haversine(current_path[i][0], current_path[i][1],
                                            current_path[i+1][0], current_path[i+1][1])
                partial = flown_distance - cum_before if 'flown_distance' in locals() else 0
                precise_flown += max(0, partial)
            precise_flown = min(precise_flown, total_distance)

        remaining = max(0, total_distance - precise_flown)
        flight_time_sec = precise_flown / st.session_state.fly_speed if st.session_state.fly_speed > 0 else 0
        eta_seconds = remaining / st.session_state.fly_speed if st.session_state.fly_speed > 0 else 0
        eta_time = datetime.now() + timedelta(seconds=eta_seconds)
        progress_pct = precise_flown / total_distance if total_distance > 0 else 0

        route = st.session_state.sim_route_outbound if st.session_state.sim_mode == "outbound" else st.session_state.sim_route_return
        completed_wp = 0
        next_wp_coord = None
        next_wp_idx = 0
        if route and current_path:
            wp_indices = []
            for wp in route:
                min_idx = 0
                min_dist = float('inf')
                for idx, pt in enumerate(current_path):
                    d = haversine(wp[0], wp[1], pt[0], pt[1])
                    if d < min_dist:
                        min_dist = d
                        min_idx = idx
                wp_indices.append(min_idx)
            for i, idx in enumerate(wp_indices):
                if idx <= current_pos_idx:
                    completed_wp = i+1
                else:
                    next_wp_idx = i
                    next_wp_coord = route[i]
                    break
            if completed_wp == len(route):
                next_wp_coord = route[-1]
                next_wp_idx = len(route)-1

        if st.session_state.flight_status == "finished":
            st.success("✅ 飞行任务已完成！")
            with st.expander("📋 查看飞行完成报告"):
                st.write(f"- **总飞行时间**：{flight_time_sec:.1f} 秒")
                st.write(f"- **总飞行距离**：{precise_flown:.1f} 米")
                st.write(f"- **飞行高度**：{st.session_state.fly_height} 米")
                st.write(f"- **最终电量**：{st.session_state.drone_battery:.1f}%")
                st.write(f"- **完成航点**：{completed_wp}/{len(route)}")
                if completed_wp > 0:
                    st.write(f"- **终点坐标**：({route[-1][0]:.6f}, {route[-1][1]:.6f})")

        st.markdown("#### 📊 飞行任务执行监控")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("🛫 飞行状态", st.session_state.flight_status.upper())
        col2.metric("⏱️ 飞行时间", f"{flight_time_sec:.1f} s" if st.session_state.flight_status in ["running", "paused", "finished"] else "-")
        col3.metric("📏 已飞距离", f"{precise_flown:.1f} m")
        col4.metric("🧭 剩余距离", f"{remaining:.1f} m")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("🛣️ 总路程", f"{total_distance:.1f} m")
        col2.metric("🕒 预计剩余", f"{eta_seconds:.1f} s")
        col3.metric("📅 预计到达", eta_time.strftime("%H:%M:%S") if st.session_state.flight_status in ["running", "paused"] else "-")
        col4.metric("📡 飞行高度", f"{st.session_state.fly_height:.1f} m")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("🪫 电量剩余", f"{st.session_state.drone_battery:.1f}%")
        if route:
            col2.metric("📍 航点进度", f"{completed_wp}/{len(route)}")
            if next_wp_coord and completed_wp < len(route):
                col3.metric("🎯 下一航点", f"#{next_wp_idx+1} ({next_wp_coord[0]:.5f}, {next_wp_coord[1]:.5f})")
            else:
                col3.metric("🎯 下一航点", "终点已到达")
        col4.metric("⚡ 电池温度", f"{st.session_state.drone_bat_temp}°C")
        st.progress(min(1.0, progress_pct))
        st.caption(f"航线完成度：{progress_pct*100:.1f}%")
        if current_pos_idx < len(current_path):
            cur_lat, cur_lon = current_path[current_pos_idx]
            st.text(f"📍 当前精确位置：({cur_lat:.6f}, {cur_lon:.6f})")

# ==================== 标签2：飞行监控 ====================
with tab2:
    st.title("📡 无人机飞行监控 - 心跳包实时监测")
    st_autorefresh(interval=1000, key="heartbeat_refresh")

    data_mode = st.radio("📂 数据源", ["实时模拟", "从 CSV 加载"], horizontal=True)
    if data_mode == "从 CSV 加载":
        if os.path.exists("heartbeat_log.csv"):
            df = pd.read_csv("heartbeat_log.csv")
            df["发送时间"] = pd.to_datetime(df["发送时间"])
            st.success("已加载 heartbeat_log.csv")
        else:
            st.error("找不到 heartbeat_log.csv")
            st.stop()
    else:
        if "sim_running" not in st.session_state:
            st.session_state.sim_running = False
        if "sim_start_time" not in st.session_state:
            st.session_state.sim_start_time = None
        if "sim_disconnected" not in st.session_state:
            st.session_state.sim_disconnected = False
        if "sim_disconnect_time" not in st.session_state:
            st.session_state.sim_disconnect_time = None

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if not st.session_state.sim_running:
                if st.button("▶️ 开始模拟", use_container_width=True):
                    st.session_state.sim_running = True
                    st.session_state.sim_start_time = datetime.now()
                    st.session_state.sim_disconnected = False
                    st.session_state.sim_disconnect_time = None
                    st.rerun()
            else:
                if st.button("⏹️ 停止模拟", use_container_width=True):
                    st.session_state.sim_running = False
                    st.rerun()
        with col_btn2:
            if st.session_state.sim_running:
                if not st.session_state.sim_disconnected:
                    if st.button("🔌 断开连接", use_container_width=True):
                        st.session_state.sim_disconnected = True
                        st.session_state.sim_disconnect_time = datetime.now()
                        st.rerun()
                else:
                    if st.button("🔗 恢复连接", use_container_width=True):
                        st.session_state.sim_disconnected = False
                        st.rerun()

        if not st.session_state.sim_running:
            df = pd.DataFrame()
        else:
            df, timeout = generate_heartbeats(
                st.session_state.sim_start_time,
                st.session_state.sim_disconnected,
                st.session_state.sim_disconnect_time
            )
            if not df.empty:
                df["发送时间"] = pd.to_datetime(df["发送时间"])
            if timeout and not st.session_state.sim_disconnected:
                st.error("🚨 连接超时！")
    if not df.empty:
        total = len(df)
        success = len(df[df["状态"] == "成功"])
        lost = len(df[df["状态"] == "丢失"])
        timeout = len(df[df["状态"] == "超时"])

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📨 总发送", total)
        col2.metric("✅ 成功", success)
        col3.metric("❌ 丢失", lost)
        col4.metric("🚨 超时", timeout)

        st.subheader("📈 心跳包序号变化")
        color_scale = alt.Scale(domain=["成功", "丢失", "超时"], range=["#2ca02c", "#ff7f0e", "#d62728"])
        chart = alt.Chart(df).mark_line(point=True).encode(
            x="发送时间:T", y="序号:Q",
            color=alt.Color("状态:N", scale=color_scale),
            tooltip=["发送时间", "序号", "状态"]
        ).properties(width=700, height=400).interactive()
        st.altair_chart(chart, use_container_width=True)

        st.subheader("📋 最近记录")
        st.dataframe(df.tail(20), use_container_width=True)
    else:
        st.info("无数据")

# ==================== 标签3：通信链路拓扑与数据流 ====================
with tab3:
    st.title("🔗 通信链路拓扑与实时数据流")
    st.markdown("**GCS (地面站) — UDP — OBC (机载计算机) — NAVLink — FCU (飞控)**")
    st_autorefresh(interval=1000, key="link_refresh")

    init_link_simulator()
    update_link_simulator()
    sim = st.session_state.link_sim

    col1, col2 = st.columns(2)
    with col1:
        gcs_status = sim["gcs_obc"]["connected"]
        if st.button("🔌 模拟GCS-OBC链路" + ("断开" if gcs_status else "恢复"), use_container_width=True):
            sim["gcs_obc"]["connected"] = not gcs_status
            st.rerun()
    with col2:
        obc_status = sim["obc_fcu"]["connected"]
        if st.button("🔌 模拟OBC-FCU链路" + ("断开" if obc_status else "恢复"), use_container_width=True):
            sim["obc_fcu"]["connected"] = not obc_status
            st.rerun()

    st.divider()
    col_node1, col_arrow1, col_node2, col_arrow2, col_node3 = st.columns([2,1,2,1,2])
    with col_node1:
        st.info("**🖥️ GCS 地面站**")
        st.caption("UDP 连接")
        status_g = "🟢 在线" if sim["gcs_obc"]["connected"] else "🔴 离线"
        st.metric("状态", status_g)
    with col_arrow1:
        st.markdown("➡️⬅️")
    with col_node2:
        st.info("**📡 OBC 机载计算机**")
        st.caption("UDP↔NAVLink 转发")
        st.metric("GCS-OBC", "🟢" if sim["gcs_obc"]["connected"] else "🔴", delta=None)
        st.metric("OBC-FCU", "🟢" if sim["obc_fcu"]["connected"] else "🔴", delta=None)
    with col_arrow2:
        st.markdown("➡️⬅️")
    with col_node3:
        st.info("**🛬 FCU 飞控**")
        st.caption("NAVLink 协议")
        status_f = "🟢 在线" if sim["obc_fcu"]["connected"] else "🔴 离线"
        st.metric("状态", status_f)

    st.divider()
    st.subheader("📶 链路性能指标")
    metrics_col1, metrics_col2 = st.columns(2)
    with metrics_col1:
        st.markdown("**GCS ↔ OBC (UDP)**")
        if sim["gcs_obc"]["connected"]:
            st.metric("延迟", f"{sim['gcs_obc']['current_delay']} ms", delta=None)
            st.metric("丢包率", f"{sim['gcs_obc']['current_loss']} %", delta=None)
        else:
            st.warning("链路断开")
    with metrics_col2:
        st.markdown("**OBC ↔ FCU (NAVLink)**")
        if sim["obc_fcu"]["connected"]:
            st.metric("延迟", f"{sim['obc_fcu']['current_delay']} ms", delta=None)
            st.metric("丢包率", f"{sim['obc_fcu']['current_loss']} %", delta=None)
        else:
            st.warning("链路断开")

    st.divider()
    st.subheader("📜 双向通信日志（分流展示）")
    downlink_logs = []
    uplink_logs = []
    for log in sim["logs"][-50:]:
        ts, direction, msg = log
        if direction in ("GCS→OBC", "OBC→FCU (NAVLink)"):
            downlink_logs.append(log)
        elif direction in ("FCU→OBC", "OBC→GCS (UDP)"):
            uplink_logs.append(log)
        else:
            downlink_logs.append(log)
            uplink_logs.append(log)

    st.markdown("**📡 下行 (GCS → FCU) - 指令/控制**")
    if downlink_logs:
        df_down = pd.DataFrame(downlink_logs, columns=["时间", "方向", "消息内容"])
        st.dataframe(df_down, use_container_width=True, height=250)
    else:
        st.info("无下行日志")

    st.markdown("**🔼 上行 (FCU → GCS) - 遥测/应答**")
    if uplink_logs:
        df_up = pd.DataFrame(uplink_logs, columns=["时间", "方向", "消息内容"])
        st.dataframe(df_up, use_container_width=True, height=250)
    else:
        st.info("无上行日志")

    st.caption("链路状态每秒自动刷新一次，延迟/丢包率为模拟数据，支持手动断开/恢复链路。")