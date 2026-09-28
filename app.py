import streamlit as st
import pandas as pd
from datetime import datetime, date
import pymysql
import os

from google import genai
from google.genai import types


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

# Host database cloud mysql - aiven
DB_CONFIG = {
    "host": "mysql-425beae-quantricongngheso.d.aivencloud.com",
    "port": 28430,
    "user": "avnadmin",
    "password": "AVNS_rh-nVNeJhxVV2BtOJfT",
    "database": "defaultdb",
    "charset": "utf8mb4",
    "ssl": {}
}


# ============================================================
# GEMINI
# ============================================================

# AI CHAT BOT
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

@st.cache_resource
def get_gemini_client():
    if not GEMINI_API_KEY:
        return None

    return genai.Client(
        api_key=GEMINI_API_KEY
    )


gemini_client = get_gemini_client()

GEMINI_MODEL = "gemini-3.8-flash"


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
    floor INT,
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
    completed INT DEFAULT 0,
    updated_at VARCHAR(255)
)
""")


cursor.execute("""
CREATE TABLE IF NOT EXISTS minibar (
    id INT PRIMARY KEY AUTO_INCREMENT,
    room_number VARCHAR(255),
    item VARCHAR(255),
    quantity INT DEFAULT 0,
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
# HÀM LẤY DATA CHO GEMINI
# ============================================================

def get_ai_data():

    rooms_data = pd.read_sql_query("""
        SELECT
            room_number,
            room_type,
            floor,
            price,
            status,
            guest_name,
            phone,
            checkin,
            checkout,
            note
        FROM rooms
        ORDER BY room_number
    """, conn)

    minibar_data = pd.read_sql_query("""
        SELECT
            room_number,
            item,
            quantity,
            price,
            quantity * price AS total
        FROM minibar
        ORDER BY room_number
    """, conn)

    transactions_data = pd.read_sql_query("""
        SELECT
            room_number,
            guest_name,
            transaction_type,
            amount,
            created_at
        FROM transactions
        ORDER BY id DESC
    """, conn)

    housekeeping_data = pd.read_sql_query("""
        SELECT
            room_number,
            task,
            completed,
            updated_at
        FROM housekeeping
        ORDER BY room_number
    """, conn)

    return {
        "rooms": rooms_data.to_json(
            orient="records",
            force_ascii=False
        ),
        "minibar": minibar_data.to_json(
            orient="records",
            force_ascii=False
        ),
        "transactions": transactions_data.to_json(
            orient="records",
            force_ascii=False
        ),
        "housekeeping": housekeeping_data.to_json(
            orient="records",
            force_ascii=False
        )
    }


def ask_gemini(question):

    if gemini_client is None:
        return (
            "Chưa cấu hình GEMINI_API_KEY. "
            "Vui lòng thêm key vào Streamlit Secrets."
        )

    try:

        data = get_ai_data()

        system_instruction = """
Bạn là trợ lý AI của ứng dụng Hotel Manager.

Bạn đang hỗ trợ người dùng sử dụng một hệ thống quản lý khách sạn.

Các bảng dữ liệu hiện có:

1. rooms
- room_number: số phòng
- room_type: loại phòng
- floor: tầng
- price: giá phòng
- status: trạng thái phòng
- guest_name: tên khách
- phone: số điện thoại
- checkin: ngày nhận phòng
- checkout: ngày trả phòng
- note: ghi chú

Các trạng thái phòng:
- Trống
- Đang ở
- Đang dọn
- Bảo trì

2. minibar
- room_number: số phòng
- item: sản phẩm
- quantity: số lượng
- price: đơn giá
- total: thành tiền

3. transactions
- room_number: số phòng
- guest_name: tên khách
- transaction_type: loại giao dịch
- amount: số tiền
- created_at: thời gian

4. housekeeping
- room_number: số phòng
- task: công việc
- completed: trạng thái hoàn thành
- updated_at: thời gian cập nhật

Quy tắc:

- Chỉ sử dụng dữ liệu được cung cấp.
- Không được tự bịa số liệu.
- Nếu dữ liệu không có, nói rõ là không có dữ liệu.
- Khi người dùng hỏi về phòng, khách, minibar hoặc doanh thu,
  hãy ưu tiên sử dụng dữ liệu thực tế được cung cấp.
- Trả lời bằng tiếng Việt.
- Trả lời ngắn gọn, dễ hiểu.
- Có thể giải thích cách sử dụng các chức năng của ứng dụng.
- Không tự thực hiện thay đổi dữ liệu trong database.
- Đây là trợ lý READ ONLY.
"""

        data_context = f"""
DỮ LIỆU THỰC TẾ HIỆN TẠI TỪ DATABASE:

ROOMS:
{data["rooms"]}

MINIBAR:
{data["minibar"]}

TRANSACTIONS:
{data["transactions"]}

HOUSEKEEPING:
{data["housekeeping"]}
"""

        history_text = ""

        if "ai_messages" in st.session_state:

            recent_messages = st.session_state.ai_messages[-10:]

            for message in recent_messages:

                role = message["role"]
                content = message["content"]

                history_text += f"""
{role.upper()}: {content}
"""

        prompt = f"""
{data_context}

LỊCH SỬ HỘI THOẠI:
{history_text}

CÂU HỎI HIỆN TẠI:
{question}
"""

        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2,
                max_output_tokens=1000
            )
        )

        return response.text

    except Exception as e:

        return f"Không thể kết nối Gemini: {str(e)}"


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
        "🤖 Trợ lý AI",
        "⚙️ Cài đặt"
    ]
)


st.sidebar.divider()


rooms = get_rooms()

total_rooms = len(rooms)

occupied = len(
    rooms[rooms["status"] == "Đang ở"]
)

available = len(
    rooms[rooms["status"] == "Trống"]
)

cleaning = len(
    rooms[rooms["status"] == "Đang dọn"]
)

maintenance = len(
    rooms[rooms["status"] == "Bảo trì"]
)


st.sidebar.metric(
    "Tổng số phòng",
    total_rooms
)

st.sidebar.metric(
    "Đang có khách",
    occupied
)


# ============================================================
# 1. TỔNG QUAN
# ============================================================

if menu == "📊 Tổng quan":

    st.title("📊 Tổng quan khách sạn")

    st.caption(
        f"Cập nhật: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )

    col1, col2, col3, col4, col5 = st.columns(5)

    col1.metric(
        "🏨 Tổng phòng",
        total_rooms
    )

    col2.metric(
        "🟢 Phòng trống",
        available
    )

    col3.metric(
        "🔴 Đang ở",
        occupied
    )

    col4.metric(
        "🧹 Đang dọn",
        cleaning
    )

    col5.metric(
        "🔧 Bảo trì",
        maintenance
    )

    st.divider()

    occupancy = 0

    if total_rooms > 0:
        occupancy = occupied / total_rooms * 100

    st.subheader("📈 Công suất phòng")

    st.progress(int(occupancy))

    st.write(
        f"**{occupancy:.1f}%** phòng đang có khách"
    )

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
            [
                "Tất cả",
                "Trống",
                "Đang ở",
                "Đang dọn",
                "Bảo trì"
            ]
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

        st.warning(
            "Hiện không có phòng trống."
        )

    else:

        with st.form("checkin_form"):

            col1, col2 = st.columns(2)

            with col1:

                room_number = st.selectbox(
                    "🛏️ Phòng",
                    available_rooms[
                        "room_number"
                    ].tolist()
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

                st.error(
                    "Vui lòng nhập tên khách."
                )

            elif checkout_date < checkin_date:

                st.error(
                    "Ngày trả phòng không được trước ngày nhận phòng."
                )

            else:

                cursor.execute("""
                    UPDATE rooms
                    SET status='Đang ở',
                        guest_name=%s,
                        phone=%s,
                        checkin=%s,
                        checkout=%s,
                        note=%s
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

        st.info(
            "Hiện không có khách đang ở."
        )

    else:

        room_number = st.selectbox(
            "Chọn phòng trả",
            occupied_rooms[
                "room_number"
            ].tolist()
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

        cursor.execute("""
            SELECT COALESCE(
                SUM(quantity * price),
                0
            )
            FROM minibar
            WHERE room_number=%s
        """, (room_number,))

        minibar_total = cursor.fetchone()[0]

        other_charge = st.number_input(
            "💳 Chi phí phát sinh khác",
            min_value=0,
            step=50000
        )

        room_price = float(
            room["price"]
        )

        total = (
            room_price
            + float(minibar_total)
            + other_charge
        )

        st.subheader(
            "💰 Tổng thanh toán"
        )

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

    item_price = dict(
        minibar_items
    )[item]

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
        SELECT
            room_number,
            item,
            quantity,
            price,
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

    transactions = pd.read_sql_query(
        """
        SELECT *
        FROM transactions
        ORDER BY id DESC
        """,
        conn
    )

    if transactions.empty:

        st.info(
            "Chưa có giao dịch."
        )

    else:

        total_revenue = transactions[
            "amount"
        ].sum()

        room_revenue = transactions[
            transactions["transaction_type"] == "Tiền phòng"
        ]["amount"].sum()

        payment_revenue = transactions[
            transactions["transaction_type"] == "Thanh toán"
        ]["amount"].sum()

        c1, c2, c3 = st.columns(3)

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

        st.divider()

        st.subheader(
            "📋 Lịch sử giao dịch"
        )

        st.dataframe(
            transactions,
            use_container_width=True,
            hide_index=True
        )

        st.subheader(
            "📊 Doanh thu theo loại"
        )

        revenue_chart = transactions.groupby(
            "transaction_type"
        )["amount"].sum()

        st.bar_chart(
            revenue_chart
        )


# ============================================================
# 8. TRỢ LÝ AI
# ============================================================

elif menu == "🤖 Trợ lý AI":

    st.title("🤖 Trợ lý AI")

    st.caption(
        "Hỏi Gemini về khách sạn, phòng, khách, minibar, "
        "doanh thu hoặc cách sử dụng hệ thống."
    )

    if not GEMINI_API_KEY:

        st.error(
            "Chưa tìm thấy GEMINI_API_KEY."
        )

        st.info(
            "Vào Streamlit Cloud → Settings → Secrets "
            "và thêm GEMINI_API_KEY."
        )

    else:

        if "ai_messages" not in st.session_state:

            st.session_state.ai_messages = []

        if not st.session_state.ai_messages:

            st.info(
                "Ví dụ: "
                "\"Hiện có bao nhiêu phòng trống?\"  \n"
                "\"Phòng nào đang có khách?\"  \n"
                "\"Doanh thu hiện tại là bao nhiêu?\"  \n"
                "\"Phòng 101 có minibar gì?\"  \n"
                "\"Làm sao để nhận phòng cho khách?\""
            )

        for message in st.session_state.ai_messages:

            with st.chat_message(
                message["role"]
            ):

                st.markdown(
                    message["content"]
                )

        user_question = st.chat_input(
            "Nhập câu hỏi..."
        )

        if user_question:

            st.session_state.ai_messages.append({
                "role": "user",
                "content": user_question
            })

            with st.chat_message("user"):

                st.markdown(
                    user_question
                )

            with st.chat_message("assistant"):

                with st.spinner(
                    "Gemini đang suy nghĩ..."
                ):

                    answer = ask_gemini(
                        user_question
                    )

                st.markdown(
                    answer
                )

            st.session_state.ai_messages.append({
                "role": "assistant",
                "content": answer
            })

        if st.session_state.ai_messages:

            st.divider()

            if st.button(
                "🗑️ Xóa lịch sử chat"
            ):

                st.session_state.ai_messages = []

                st.rerun()


# ============================================================
# 9. CÀI ĐẶT
# ============================================================

elif menu == "⚙️ Cài đặt":

    st.title("⚙️ Cài đặt hệ thống")

    st.subheader(
        "➕ Thêm phòng mới"
    )

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

            st.error(
                "Vui lòng nhập số phòng."
            )

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

    st.subheader(
        "🗑️ Xóa phòng"
    )

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
# FOOTER
# ============================================================

st.sidebar.divider()

st.sidebar.caption(
    "🏨 Hotel Manager v1.0"
)

st.sidebar.caption(
    "Quản lý phòng • Khách • Buồng phòng • Minibar • Doanh thu"
)
