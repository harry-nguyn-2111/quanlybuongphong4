import streamlit as st
import pandas as pd
from datetime import datetime, date
import pymysql
import os
import json
import io
from openai import OpenAI
st.image("VT.png", width=2000)
# ============================================================
# CẤU HÌNH
# ============================================================

st.set_page_config(
    page_title="Hotel Manager",
    page_icon="🏨",
    layout="wide",
    initial_sidebar_state="expanded"
)

DB_CONFIG = {
    "host": "mysql-425beae-quantricongngheso.d.aivencloud.com",
    "port": 28430,
    "user": "avnadmin",
    "password": "AVNS_rh-nVNeJhxVV2BtOJfT",
    "database": "defaultdb",
    "charset": "utf8mb4",
    "ssl": {}
}

# API key is stored in Streamlit Secrets, not in the source code.
OPENROUTER_API_KEY = st.secrets.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = "openrouter/free"

# ============================================================
# DATABASE
# ============================================================

def get_connection():
    return pymysql.connect(**DB_CONFIG)


conn = get_connection()
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS rooms (
    id INT PRIMARY KEY AUTO_INCREMENT,
    room_number VARCHAR(255) UNIQUE,
    room_type VARCHAR(255),
    floor INTEGER,
    price DECIMAL(10,2),
    status VARCHAR(255) DEFAULT 'Trống',
    guest_name VARCHAR(255) DEFAULT '',
    phone VARCHAR(255) DEFAULT '',
    checkin VARCHAR(255) DEFAULT '',
    checkout VARCHAR(255) DEFAULT '',
    note VARCHAR(255) DEFAULT ''
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS housekeeping (
    id INT PRIMARY KEY AUTO_INCREMENT,
    room_number VARCHAR(255),
    task VARCHAR(255),
    completed INTEGER DEFAULT 0,
    updated_at VARCHAR(255)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS minibar (
    id INT PRIMARY KEY AUTO_INCREMENT,
    room_number VARCHAR(255),
    item VARCHAR(255),
    quantity INTEGER DEFAULT 0,
    price DECIMAL(10,2) DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    room_number VARCHAR(255),
    guest_name VARCHAR(255),
    transaction_type VARCHAR(255),
    amount DECIMAL(10,2),
    created_at VARCHAR(255)
)
""")

conn.commit()

# ============================================================
# DỮ LIỆU MẶC ĐỊNH
# ============================================================

default_rooms = [
    ("101", "Standard", 1, 500000),
    ("102", "Standard", 1, 500000),
    ("103", "Standard", 1, 500000),
    ("104", "Deluxe", 1, 700000),
    ("105", "Deluxe", 1, 700000),
    ("201", "Standard", 2, 500000),
    ("202", "Standard", 2, 500000),
    ("203", "Deluxe", 2, 700000),
    ("204", "Deluxe", 2, 700000),
    ("205", "Suite", 2, 1200000),
]

for room in default_rooms:
    cursor.execute("""
        INSERT IGNORE INTO rooms
        (room_number, room_type, floor, price)
        VALUES (%s, %s, %s, %s)
    """, room)

conn.commit()

# ============================================================
# HÀM TIỆN ÍCH
# ============================================================

def money(value):
    return f"{value:,.0f} VNĐ"


def get_rooms():
    return pd.read_sql_query(
        "SELECT * FROM rooms ORDER BY room_number",
        conn
    )


def update_room_status(room_number, status):
    cursor.execute(
        "UPDATE rooms SET status=%s WHERE room_number=%s",
        (status, room_number)
    )
    conn.commit()


def add_transaction(room_number, guest_name, transaction_type, amount):
    cursor.execute("""
        INSERT INTO transactions
        (room_number, guest_name, transaction_type, amount, created_at)
        VALUES (%s, %s, %s, %s, %s)
    """, (
        room_number,
        guest_name,
        transaction_type,
        amount,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()




# ============================================================
# OPENROUTER AI ASSISTANT
# ============================================================

def get_openrouter_client():
    if not OPENROUTER_API_KEY:
        return None

    return OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "https://streamlit.io/",
            "X-Title": "Hotel Manager"
        }
    )


openrouter_client = get_openrouter_client()


def get_ai_data():
    """Read current hotel data so the AI can answer app/data questions."""
    data = {}

    data["rooms"] = pd.read_sql_query(
        """
        SELECT
            room_number, room_type, floor, price, status,
            guest_name, phone, checkin, checkout, note
        FROM rooms
        ORDER BY room_number
        """,
        conn
    ).to_dict(orient="records")

    data["minibar"] = pd.read_sql_query(
        """
        SELECT room_number, item, quantity, price,
               quantity * price AS total
        FROM minibar
        ORDER BY id DESC
        LIMIT 100
        """,
        conn
    ).to_dict(orient="records")

    data["transactions"] = pd.read_sql_query(
        """
        SELECT room_number, guest_name, transaction_type, amount, created_at
        FROM transactions
        ORDER BY id DESC
        LIMIT 100
        """,
        conn
    ).to_dict(orient="records")

    data["housekeeping"] = pd.read_sql_query(
        """
        SELECT room_number, task, completed, updated_at
        FROM housekeeping
        ORDER BY id DESC
        LIMIT 100
        """,
        conn
    ).to_dict(orient="records")

    return data


def ask_openrouter(question):
    if not OPENROUTER_API_KEY or openrouter_client is None:
        return "Chưa cấu hình OPENROUTER_API_KEY trong Streamlit Secrets."

    try:
        ai_data = get_ai_data()

        history = st.session_state.get("ai_messages", [])[-10:]
        history_text = "\n".join(
            f"{m['role']}: {m['content']}"
            for m in history
        )

        system_instruction = """
Bạn là trợ lý AI của ứng dụng Hotel Manager.
Bạn trả lời bằng tiếng Việt, ngắn gọn, rõ ràng và thực tế.
Bạn có quyền READ ONLY đối với dữ liệu khách sạn được cung cấp trong prompt.
Không được tự ý tạo, sửa hoặc xóa dữ liệu trong database.
Khi câu hỏi liên quan dữ liệu hiện tại, chỉ dùng dữ liệu được cung cấp.
Nếu dữ liệu không đủ để kết luận, hãy nói rõ là chưa có đủ dữ liệu.
Khi giải thích cách dùng ứng dụng, dựa trên các chức năng thật sự có trong app.
"""

        prompt = f"""
CÂU HỎI CỦA NGƯỜI DÙNG:
{question}

DỮ LIỆU HIỆN TẠI CỦA HOTEL MANAGER (JSON):
{json.dumps(ai_data, ensure_ascii=False, default=str)}

LỊCH SỬ CHAT GẦN ĐÂY:
{history_text}

Hãy trả lời trực tiếp câu hỏi của người dùng.
"""

        response = openrouter_client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=1000
        )

        return response.choices[0].message.content

    except Exception as e:
        error_text = str(e)

        if "429" in error_text:
            return "OpenRouter đang giới hạn request hoặc free model đang quá tải. Hãy thử lại sau."

        if "401" in error_text:
            return "OPENROUTER_API_KEY không hợp lệ hoặc chưa được cấp quyền."

        if "402" in error_text:
            return "Model bạn đang gọi không nằm trong free tier hoặc tài khoản không đủ credit."

        if "404" in error_text:
            return f"Không tìm thấy model OpenRouter: {OPENROUTER_MODEL}."

        return f"Không thể kết nối OpenRouter: {error_text}"


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.title("🏨 HOTEL MANAGER")
st.sidebar.caption("Hệ thống quản lý khách sạn")

menu = st.sidebar.radio(
    "MENU",
    [
        "📊 Tổng quan",
        "🛏️ Quản lý phòng",
        "📋 Nhận phòng",
        "🚪 Trả phòng",
        "🧹 Buồng phòng",
        "🍾 Minibar",
        "💰 Doanh thu",
        "⚙️ Cài đặt",
        "🤖 Trợ lý AI"
    ]
)

st.sidebar.divider()

rooms = get_rooms()

total_rooms = len(rooms)
occupied = len(rooms[rooms["status"] == "Đang ở"])
available = len(rooms[rooms["status"] == "Trống"])
cleaning = len(rooms[rooms["status"] == "Đang dọn"])
maintenance = len(rooms[rooms["status"] == "Bảo trì"])

st.sidebar.metric("Tổng số phòng", total_rooms)
st.sidebar.metric("Đang có khách", occupied)


# ============================================================
# 1. TỔNG QUAN
# ============================================================

if menu == "📊 Tổng quan":

    st.title("📊 Tổng quan khách sạn")
    st.caption(
        f"Cập nhật: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )

    col1, col2, col3, col4, col5 = st.columns(5)

    col1.metric("🏨 Tổng phòng", total_rooms)
    col2.metric("🟢 Phòng trống", available)
    col3.metric("🔴 Đang ở", occupied)
    col4.metric("🧹 Đang dọn", cleaning)
    col5.metric("🔧 Bảo trì", maintenance)

    st.divider()

    # Công suất phòng
    occupancy = 0
    if total_rooms > 0:
        occupancy = occupied / total_rooms * 100

    st.subheader("📈 Công suất phòng")

    st.progress(int(occupancy))
    st.write(f"**{occupancy:.1f}%** phòng đang có khách")

    st.divider()

    st.subheader("🛏️ Tình trạng phòng")

    cols = st.columns(5)

    status_colors = {
        "Trống": "🟢",
        "Đang ở": "🔴",
        "Đang dọn": "🟡",
        "Bảo trì": "⚫"
    }

    for index, room in rooms.iterrows():

        col = cols[index % 5]

        with col:
            st.markdown(
                f"""
                ### {room['room_number']}
                {status_colors.get(room['status'], "⚪")} **{room['status']}**
                
                Loại: {room['room_type']}  
                Giá: {money(room['price'])}
                """
            )


# ============================================================
# 2. QUẢN LÝ PHÒNG
# ============================================================

elif menu == "🛏️ Quản lý phòng":

    st.title("🛏️ Quản lý phòng")

    rooms = get_rooms()

    col1, col2 = st.columns(2)

    with col1:
        filter_status = st.selectbox(
            "Lọc theo trạng thái",
            ["Tất cả", "Trống", "Đang ở", "Đang dọn", "Bảo trì"]
        )

    with col2:
        search = st.text_input(
            "🔎 Tìm số phòng"
        )

    filtered = rooms.copy()

    if filter_status != "Tất cả":
        filtered = filtered[
            filtered["status"] == filter_status
        ]

    if search:
        filtered = filtered[
            filtered["room_number"].str.contains(
                search,
                case=False
            )
        ]

    st.dataframe(
        filtered[
            [
                "room_number",
                "room_type",
                "floor",
                "price",
                "status",
                "guest_name",
                "phone",
                "checkin",
                "checkout"
            ]
        ],
        use_container_width=True,
        hide_index=True,
        column_config={
            "room_number": "Phòng",
            "room_type": "Loại phòng",
            "floor": "Tầng",
            "price": st.column_config.NumberColumn(
                "Giá phòng",
                format="%d VNĐ"
            ),
            "status": "Trạng thái",
            "guest_name": "Khách",
            "phone": "SĐT",
            "checkin": "Check-in",
            "checkout": "Check-out"
        }
    )

    st.divider()

    st.subheader("🔄 Thay đổi trạng thái phòng")

    room_number = st.selectbox(
        "Chọn phòng",
        rooms["room_number"].tolist()
    )

    new_status = st.selectbox(
        "Trạng thái mới",
        [
            "Trống",
            "Đang ở",
            "Đang dọn",
            "Bảo trì"
        ]
    )

    if st.button(
        "💾 Cập nhật trạng thái",
        type="primary"
    ):
        update_room_status(
            room_number,
            new_status
        )

        st.success(
            f"Phòng {room_number} → {new_status}"
        )

        st.rerun()


# ============================================================
# 3. NHẬN PHÒNG
# ============================================================

elif menu == "📋 Nhận phòng":

    st.title("📋 Nhận phòng")

    available_rooms = rooms[
        rooms["status"] == "Trống"
    ]

    if available_rooms.empty:

        st.warning("Hiện không có phòng trống.")

    else:

        with st.form("checkin_form"):

            col1, col2 = st.columns(2)

            with col1:

                room_number = st.selectbox(
                    "🛏️ Phòng",
                    available_rooms["room_number"].tolist()
                )

                guest_name = st.text_input(
                    "👤 Tên khách *"
                )

                phone = st.text_input(
                    "📱 Số điện thoại"
                )

            with col2:

                checkin_date = st.date_input(
                    "📅 Ngày nhận phòng",
                    date.today()
                )

                checkout_date = st.date_input(
                    "📅 Ngày trả phòng",
                    date.today()
                )

                note = st.text_area(
                    "📝 Ghi chú"
                )

            submit = st.form_submit_button(
                "✅ Xác nhận nhận phòng",
                type="primary"
            )

        if submit:

            if not guest_name.strip():

                st.error("Vui lòng nhập tên khách.")

            elif checkout_date < checkin_date:

                st.error(
                    "Ngày trả phòng không được trước ngày nhận phòng."
                )

            else:

                cursor.execute("""
                    UPDATE rooms
                    SET status='Đang ở',
                        guest_name=?,
                        phone=?,
                        checkin=?,
                        checkout=?,
                        note=?
                    WHERE room_number=%s
                """, (
                    guest_name,
                    phone,
                    str(checkin_date),
                    str(checkout_date),
                    note,
                    room_number
                ))

                conn.commit()

                room_data = rooms[
                    rooms["room_number"] == room_number
                ].iloc[0]

                add_transaction(
                    room_number,
                    guest_name,
                    "Tiền phòng",
                    room_data["price"]
                )

                st.success(
                    f"✅ Đã nhận phòng {room_number} cho {guest_name}"
                )

                st.rerun()


# ============================================================
# 4. TRẢ PHÒNG
# ============================================================

elif menu == "🚪 Trả phòng":

    st.title("🚪 Trả phòng")

    occupied_rooms = rooms[
        rooms["status"] == "Đang ở"
    ]

    if occupied_rooms.empty:

        st.info("Hiện không có khách đang ở.")

    else:

        room_number = st.selectbox(
            "Chọn phòng trả",
            occupied_rooms["room_number"].tolist()
        )

        room = occupied_rooms[
            occupied_rooms["room_number"] == room_number
        ].iloc[0]

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Phòng",
            room["room_number"]
        )

        col2.metric(
            "Khách",
            room["guest_name"]
        )

        col3.metric(
            "Giá phòng",
            money(room["price"])
        )

        st.divider()

        minibar_total = cursor.execute("""
            SELECT COALESCE(SUM(quantity * price), 0)
            FROM minibar
            WHERE room_number=%s
        """, (room_number,)).fetchone()[0]

        other_charge = st.number_input(
            "💳 Chi phí phát sinh khác",
            min_value=0,
            step=50000
        )

        room_price = float(room["price"])

        total = room_price + minibar_total + other_charge

        st.subheader("💰 Tổng thanh toán")

        c1, c2, c3, c4 = st.columns(4)

        c1.metric(
            "Tiền phòng",
            money(room_price)
        )

        c2.metric(
            "Minibar",
            money(minibar_total)
        )

        c3.metric(
            "Phát sinh",
            money(other_charge)
        )

        c4.metric(
            "TỔNG",
            money(total)
        )

        if st.button(
            "🚪 Xác nhận trả phòng",
            type="primary"
        ):

            add_transaction(
                room_number,
                room["guest_name"],
                "Thanh toán",
                total
            )

            cursor.execute("""
                UPDATE rooms
                SET status='Đang dọn',
                    guest_name='',
                    phone='',
                    checkin='',
                    checkout='',
                    note=''
                WHERE room_number=%s
            """, (room_number,))

            cursor.execute("""
                DELETE FROM minibar
                WHERE room_number=%s
            """, (room_number,))

            conn.commit()

            st.success(
                f"Đã trả phòng {room_number}. "
                f"Tổng thanh toán: {money(total)}"
            )

            st.rerun()


# ============================================================
# 5. BUỒNG PHÒNG
# ============================================================

elif menu == "🧹 Buồng phòng":

    st.title("🧹 Quản lý buồng phòng")

    rooms = get_rooms()

    room_number = st.selectbox(
        "Chọn phòng",
        rooms["room_number"].tolist()
    )

    st.divider()

    tasks = [
        "Dọn phòng",
        "Thay ga giường",
        "Thay khăn",
        "Dọn nhà vệ sinh",
        "Hút bụi",
        "Lau sàn",
        "Kiểm tra minibar",
        "Kiểm tra TV",
        "Kiểm tra điều hòa",
        "Kiểm tra đèn",
        "Bổ sung nước uống",
        "Bổ sung đồ vệ sinh",
        "Kiểm tra tài sản trong phòng"
    ]

    st.subheader(
        f"📋 Checklist phòng {room_number}"
    )

    completed_tasks = []

    for task in tasks:

        checked = st.checkbox(
            task,
            key=f"{room_number}_{task}"
        )

        if checked:
            completed_tasks.append(task)

    progress = len(completed_tasks) / len(tasks)

    st.progress(progress)

    st.write(
        f"Hoàn thành **{len(completed_tasks)}/{len(tasks)}** công việc"
    )

    if st.button(
        "✅ Hoàn thành vệ sinh",
        type="primary"
    ):

        if len(completed_tasks) < len(tasks):

            st.warning(
                "Bạn chưa hoàn thành toàn bộ checklist."
            )

        else:

            update_room_status(
                room_number,
                "Trống"
            )

            st.success(
                f"Phòng {room_number} đã sẵn sàng bán."
            )

            st.rerun()


# ============================================================
# 6. MINIBAR
# ============================================================

elif menu == "🍾 Minibar":

    st.title("🍾 Quản lý Minibar")

    rooms = get_rooms()

    room_number = st.selectbox(
        "Chọn phòng",
        rooms["room_number"].tolist()
    )

    minibar_items = [
        ("Nước suối", 15000),
        ("Coca Cola", 20000),
        ("Pepsi", 20000),
        ("Bia", 30000),
        ("Snack", 25000),
        ("Chocolate", 35000),
        ("Cà phê", 25000)
    ]

    item_names = [
        item[0]
        for item in minibar_items
    ]

    item = st.selectbox(
        "Sản phẩm",
        item_names
    )

    item_price = dict(minibar_items)[item]

    quantity = st.number_input(
        "Số lượng",
        min_value=1,
        value=1,
        step=1
    )

    st.write(
        f"Đơn giá: **{money(item_price)}**"
    )

    if st.button(
        "➕ Thêm Minibar",
        type="primary"
    ):

        cursor.execute("""
            INSERT INTO minibar
            (room_number, item, quantity, price)
            VALUES (%s, %s, %s, %s)
        """, (
            room_number,
            item,
            quantity,
            item_price
        ))

        conn.commit()

        st.success(
            f"Đã thêm {quantity} x {item}"
        )

        st.rerun()

    st.divider()

    minibar_data = pd.read_sql_query("""
        SELECT room_number, item, quantity, price,
               quantity * price AS total
        FROM minibar
        WHERE room_number=%s
    """, conn, params=(room_number,))

    if not minibar_data.empty:

        st.dataframe(
            minibar_data,
            use_container_width=True,
            hide_index=True
        )

        total = minibar_data["total"].sum()

        st.metric(
            "Tổng Minibar",
            money(total)
        )

    else:

        st.info(
            "Phòng này chưa có sản phẩm minibar."
        )


# ============================================================
# 7. DOANH THU
# ============================================================

elif menu == "💰 Doanh thu":

    st.title("💰 Doanh thu")
    st.caption("Theo dõi doanh thu, biểu đồ và dữ liệu giao dịch theo khoảng ngày.")

    transactions = pd.read_sql_query(
        "SELECT * FROM transactions ORDER BY id DESC",
        conn
    )

    if transactions.empty:

        st.info("Chưa có giao dịch.")

    else:

        transactions["created_at"] = pd.to_datetime(
            transactions["created_at"],
            errors="coerce"
        )
        transactions["amount"] = pd.to_numeric(
            transactions["amount"],
            errors="coerce"
        ).fillna(0)

        valid_dates = transactions["created_at"].dropna()

        if valid_dates.empty:
            st.warning("Không có giao dịch nào có ngày hợp lệ để lọc.")
        else:
            min_date = valid_dates.min().date()
            max_date = valid_dates.max().date()

            st.subheader("📅 Bộ lọc ngày")

            date_col1, date_col2 = st.columns(2)

            with date_col1:
                start_date = st.date_input(
                    "Từ ngày",
                    value=min_date,
                    min_value=min_date,
                    max_value=max_date
                )

            with date_col2:
                end_date = st.date_input(
                    "Đến ngày",
                    value=max_date,
                    min_value=min_date,
                    max_value=max_date
                )

            if start_date > end_date:
                st.error("Ngày bắt đầu không được lớn hơn ngày kết thúc.")
                st.stop()

            filtered_transactions = transactions[
                transactions["created_at"].dt.date.between(
                    start_date,
                    end_date
                )
            ].copy()

            st.divider()

            if filtered_transactions.empty:
                st.info("Không có giao dịch trong khoảng ngày đã chọn.")
            else:
                total_revenue = filtered_transactions["amount"].sum()

                room_revenue = filtered_transactions[
                    filtered_transactions["transaction_type"] == "Tiền phòng"
                ]["amount"].sum()

                payment_revenue = filtered_transactions[
                    filtered_transactions["transaction_type"] == "Thanh toán"
                ]["amount"].sum()

                transaction_count = len(filtered_transactions)

                c1, c2, c3, c4 = st.columns(4)

                c1.metric(
                    "💰 Tổng doanh thu",
                    money(total_revenue)
                )

                c2.metric(
                    "🛏️ Tiền phòng",
                    money(room_revenue)
                )

                c3.metric(
                    "💳 Thanh toán",
                    money(payment_revenue)
                )

                c4.metric(
                    "🧾 Số giao dịch",
                    transaction_count
                )

                st.divider()

                # ========================================================
                # BIỂU ĐỒ DOANH THU THEO NGÀY
                # ========================================================

                st.subheader("📈 Doanh thu theo ngày")

                daily_revenue = (
                    filtered_transactions
                    .assign(date=filtered_transactions["created_at"].dt.date)
                    .groupby("date", as_index=True)["amount"]
                    .sum()
                )

                st.line_chart(
                    daily_revenue,
                    use_container_width=True
                )

                st.divider()

                chart_col1, chart_col2 = st.columns(2)

                with chart_col1:
                    st.subheader("🥧 Doanh thu theo loại")

                    revenue_by_type = (
                        filtered_transactions
                        .groupby("transaction_type")["amount"]
                        .sum()
                        .sort_values(ascending=False)
                    )

                    pie_data = revenue_by_type.reset_index()
                    pie_data.columns = ["Loại giao dịch", "Doanh thu"]

                    st.vega_lite_chart(
                        pie_data,
                        {
                            "mark": {"type": "arc", "innerRadius": 0},
                            "encoding": {
                                "theta": {"field": "Doanh thu", "type": "quantitative"},
                                "color": {"field": "Loại giao dịch", "type": "nominal"},
                                "tooltip": [
                                    {"field": "Loại giao dịch", "type": "nominal"},
                                    {"field": "Doanh thu", "type": "quantitative", "format": ",.0f"}
                                ]
                            },
                            "height": 320
                        },
                        use_container_width=True
                    )

                with chart_col2:
                    st.subheader("🏨 Doanh thu theo phòng")

                    revenue_by_room = (
                        filtered_transactions
                        .groupby("room_number")["amount"]
                        .sum()
                        .sort_values(ascending=False)
                    )

                    st.bar_chart(
                        revenue_by_room,
                        use_container_width=True
                    )

                st.divider()

                # ========================================================
                # DATA TABLE
                # ========================================================

                st.subheader("📋 Data table")

                table_data = filtered_transactions.copy()
                table_data["created_at"] = table_data["created_at"].dt.strftime(
                    "%d/%m/%Y %H:%M:%S"
                )

                table_data = table_data[
                    [
                        "id",
                        "room_number",
                        "guest_name",
                        "transaction_type",
                        "amount",
                        "created_at"
                    ]
                ].rename(columns={
                    "id": "ID",
                    "room_number": "Phòng",
                    "guest_name": "Khách",
                    "transaction_type": "Loại giao dịch",
                    "amount": "Số tiền",
                    "created_at": "Thời gian"
                })

                st.dataframe(
                    table_data,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Số tiền": st.column_config.NumberColumn(
                            "Số tiền",
                            format="%d VNĐ"
                        )
                    }
                )

                # ========================================================
                # EXPORT EXCEL
                # ========================================================

                st.subheader("📥 Xuất Excel")

                export_data = table_data.copy()
                export_data["Số tiền"] = pd.to_numeric(
                    export_data["Số tiền"],
                    errors="coerce"
                ).fillna(0)

                output = io.BytesIO()

                with pd.ExcelWriter(
                    output,
                    engine="xlsxwriter",
                    datetime_format="dd/mm/yyyy hh:mm:ss"
                ) as writer:
                    export_data.to_excel(
                        writer,
                        index=False,
                        sheet_name="Doanh thu"
                    )

                    workbook = writer.book
                    worksheet = writer.sheets["Doanh thu"]

                    header_format = workbook.add_format({
                        "bold": True,
                        "align": "center",
                        "valign": "vcenter",
                        "border": 1
                    })

                    money_format = workbook.add_format({
                        "num_format": "#,##0 \"VNĐ\""
                    })

                    for col_num, value in enumerate(export_data.columns.values):
                        worksheet.write(0, col_num, value, header_format)

                    amount_col = export_data.columns.get_loc("Số tiền")
                    worksheet.set_column(amount_col, amount_col, 18, money_format)
                    worksheet.set_column(0, len(export_data.columns) - 1, 18)

                    # Summary sheet
                    summary = pd.DataFrame({
                        "Chỉ số": [
                            "Từ ngày",
                            "Đến ngày",
                            "Tổng doanh thu",
                            "Tiền phòng",
                            "Thanh toán",
                            "Số giao dịch"
                        ],
                        "Giá trị": [
                            str(start_date),
                            str(end_date),
                            total_revenue,
                            room_revenue,
                            payment_revenue,
                            transaction_count
                        ]
                    })

                    summary.to_excel(
                        writer,
                        index=False,
                        sheet_name="Tổng quan"
                    )

                    summary_ws = writer.sheets["Tổng quan"]
                    summary_ws.set_column(0, 0, 22)
                    summary_ws.set_column(1, 1, 20)
                    summary_ws.write(0, 0, "Chỉ số", header_format)
                    summary_ws.write(0, 1, "Giá trị", header_format)

                    summary_ws.write(2, 1, float(total_revenue), money_format)
                    summary_ws.write(3, 1, float(room_revenue), money_format)
                    summary_ws.write(4, 1, float(payment_revenue), money_format)

                output.seek(0)

                st.download_button(
                    label="⬇️ Tải file Excel",
                    data=output.getvalue(),
                    file_name=f"doanh_thu_{start_date}_{end_date}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary"
                )


# ============================================================
# 8. CÀI ĐẶT
# ============================================================

elif menu == "⚙️ Cài đặt":

    st.title("⚙️ Cài đặt hệ thống")

    st.subheader("➕ Thêm phòng mới")

    with st.form("add_room"):

        room_number = st.text_input(
            "Số phòng"
        )

        room_type = st.selectbox(
            "Loại phòng",
            [
                "Standard",
                "Deluxe",
                "Suite",
                "Family",
                "VIP"
            ]
        )

        floor = st.number_input(
            "Tầng",
            min_value=1,
            value=1
        )

        price = st.number_input(
            "Giá phòng",
            min_value=0,
            value=500000,
            step=50000
        )

        submit = st.form_submit_button(
            "➕ Thêm phòng"
        )

    if submit:

        if not room_number:

            st.error("Vui lòng nhập số phòng.")

        else:

            try:

                cursor.execute("""
                    INSERT INTO rooms
                    (room_number, room_type, floor, price)
                    VALUES (%s, %s, %s, %s)
                """, (
                    room_number,
                    room_type,
                    floor,
                    price
                ))

                conn.commit()

                st.success(
                    f"Đã thêm phòng {room_number}"
                )

                st.rerun()

            except pymysql.IntegrityError:

                st.error(
                    "Số phòng này đã tồn tại."
                )

    st.divider()

    st.subheader("🗑️ Xóa phòng")

    rooms = get_rooms()

    delete_room = st.selectbox(
        "Chọn phòng muốn xóa",
        rooms["room_number"].tolist()
    )

    if st.button(
        "🗑️ Xóa phòng",
        type="secondary"
    ):

        cursor.execute(
            "DELETE FROM rooms WHERE room_number=%s",
            (delete_room,)
        )

        conn.commit()

        st.success(
            f"Đã xóa phòng {delete_room}"
        )

        st.rerun()


# ============================================================
# 9. TRỢ LÝ AI
# ============================================================

elif menu == "🤖 Trợ lý AI":

    st.title("🤖 Trợ lý AI")
    st.caption("Hỏi về tình trạng phòng, khách, minibar, doanh thu hoặc cách sử dụng hệ thống.")

    if not OPENROUTER_API_KEY:
        st.warning("Chưa cấu hình OPENROUTER_API_KEY. Hãy thêm API key vào Streamlit Secrets.")
    else:
        if "ai_messages" not in st.session_state:
            st.session_state.ai_messages = []

        for message in st.session_state.ai_messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        question = st.chat_input("Ví dụ: Hiện có bao nhiêu phòng trống?")

        if question:
            st.session_state.ai_messages.append({
                "role": "user",
                "content": question
            })

            with st.chat_message("user"):
                st.markdown(question)

            with st.chat_message("assistant"):
                with st.spinner("Đang xử lý..."):
                    answer = ask_openrouter(question)
                st.markdown(answer)

            st.session_state.ai_messages.append({
                "role": "assistant",
                "content": answer
            })

        if st.button("🗑️ Xóa lịch sử chat"):
            st.session_state.ai_messages = []
            st.rerun()


# ============================================================
# FOOTER
# ============================================================

st.sidebar.divider()

st.sidebar.caption(
    "🏨 Hotel Manager v1.0"
)

st.sidebar.caption(
    "Quản lý phòng • Khách • Buồng phòng • Minibar • Doanh thu"
)
