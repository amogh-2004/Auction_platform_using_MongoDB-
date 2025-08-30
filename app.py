import streamlit as st
import pandas as pd
import pymongo
from bson.objectid import ObjectId
from datetime import datetime, timedelta
import bcrypt
# import timestream

client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["auction_platform"]
users_col = db["users"]
auctions_col = db["auctions"]

users_col.create_index("username", unique=True)

def register_user(username, password, role, email):
    if users_col.find_one({"username": username}):
        return False, "Username already exists!"
    if users_col.find_one({"email": email}):
        return False, "Email already exists!"
    
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    users_col.insert_one({
        "username": username,
        "email": email,
        "password": hashed,
        "role": role
    })
    return True, "User registered successfully!"


def login_user(username, password):
    user = users_col.find_one({"username": username})
    if user and bcrypt.checkpw(password.encode("utf-8"), user["password"]):
        return True, user
    return False, None

def create_auction(item_name, description, base_price, seller, duration=60):
    end_time = datetime.utcnow() + timedelta(seconds=duration)
    auctions_col.insert_one({
        "item_name": item_name,
        "description": description,
        "base_price": base_price,
        "seller": seller,
        "current_highest_bid": base_price,
        "highest_bidder": None,
        "bids": [],
        "end_time": end_time,
        "active": True
    })

def place_bid(auction_id, bidder, bid_amount):
    auction = auctions_col.find_one({"_id": ObjectId(auction_id)})
    if not auction or not auction["active"]:
        return False, "Auction not active"
    if bid_amount <= auction["current_highest_bid"]:
        return False, "Bid must be higher than current highest"
    auctions_col.update_one(
        {"_id": ObjectId(auction_id)},
        {"$set": {
            "current_highest_bid": bid_amount,
            "highest_bidder": bidder
        },
         "$push": {"bids": {"bidder": bidder, "amount": bid_amount, "time": datetime.utcnow()}}}
    )
    return True, "Bid placed successfully!"

def close_finished_auctions():
    now = datetime.utcnow()
    auctions_col.update_many(
        {"end_time": {"$lt": now}, "active": True},
        {"$set": {"active": False}}
    )

# Streamlit App 
st.set_page_config(page_title="Auction Platform", layout="wide")

with st.sidebar:
    st.title("🔑 User Panel")

    if "user" not in st.session_state:
        tab1, tab2 = st.tabs(["Register", "Login"])

        with tab1:
            username = st.text_input("New Username")
            email = st.text_input("Email")   # 👈 Added
            password = st.text_input("New Password", type="password")
            role = st.selectbox("Role", ["buyer", "seller"])
            if st.button("Register"):
                success, msg = register_user(username, password, role, email)  # 👈 Pass email
                if success:
                    st.success(msg)
                else:
                    st.error(msg)

        with tab2:
            login_usern = st.text_input("Username")
            login_pass = st.text_input("Password", type="password")
            if st.button("Login"):
                success, user = login_user(login_usern, login_pass)
                if success:
                    st.session_state.user = {"id": str(user["_id"]), "username": user["username"], "role": user["role"]}
                    st.success("Login successful!")
                else:
                    st.error("Invalid credentials")

    else:
        st.write(f"👋 Welcome, **{st.session_state.user['username']}** ({st.session_state.user['role']})")
        if st.button("Logout"):
            del st.session_state.user
            st.success("Logged out!")

if "user" not in st.session_state:
    st.stop()

tabs = st.tabs(["🏠 Home", "⚡ Auctions", "📜 History"])
user = st.session_state.user

# Home Tab 
with tabs[0]:
    st.header("🏠 Current Auction")
    close_finished_auctions()
    auction = auctions_col.find_one({"active": True}, sort=[("end_time", 1)])

    if auction:
        col1, col2 = st.columns([2, 1])
        with col1:
            st.subheader(f"{auction['item_name']} (Base: ${auction['base_price']:.2f})")
            st.write(f"**Description:** {auction['description']}")
            st.write(f"**Seller:** {auction['seller']}")
        with col2:
            remaining = (auction["end_time"] - datetime.utcnow()).total_seconds()
            st.metric("⏳ Time Remaining (s)", f"{int(remaining)}")
            if auction["highest_bidder"]:
                top_bidder = users_col.find_one({"_id": ObjectId(auction['highest_bidder'])})
                st.metric("💰 Top Bid", f"${auction['current_highest_bid']:.2f}")
                st.metric("🏆 Top Buyer", top_bidder["username"] if top_bidder else "Unknown")
            else:
                st.write("No bids yet.")

        if auction["bids"]:
            st.subheader("📊 Top Bidders")
            bids_df = pd.DataFrame(auction["bids"])
            bids_df["time"] = pd.to_datetime(bids_df["time"])
            st.table(bids_df.sort_values("amount", ascending=False).head(5))
    else:
        st.info("No active auctions right now!")

# Auctions Tab 
with tabs[1]:
    st.header("⚡ Auctions")

    if user["role"] == "seller":
        st.subheader("📦 Create Auction Item")
        item_name = st.text_input("Item Name")
        desc = st.text_area("Description")
        base = st.number_input("Base Price", min_value=1.0)
        duration = st.slider("Duration (seconds)", 30, 300, 60)
        if st.button("Start Auction"):
            create_auction(item_name, desc, base, user["username"], duration)
            st.success("Auction started!")

    if user["role"] == "buyer":
        st.subheader("💰 Active Auctions")
        close_finished_auctions()
        active_auctions = list(auctions_col.find({"active": True}))
        if not active_auctions:
            st.info("No active auctions available.")
        for item in active_auctions:
            with st.expander(f"{item['item_name']} (Current: ${item['current_highest_bid']:.2f})"):
                st.write(item["description"])
                st.write(f"Seller: {item['seller']}")
                bid_input = st.text_input(
                    f"Your Bid for {item['item_name']}",
                    key=str(item["_id"])
                )

                if st.button(f"Place Bid on {item['item_name']}", key=f"btn_{item['_id']}"):
                    try:
                        bid_amt = float(bid_input)
                        if bid_amt <= item["current_highest_bid"]:
                            st.error("Bid must be higher than current highest!")
                        else:
                            success, msg = place_bid(item["_id"], user["id"], bid_amt)
                            if success:
                                st.success(msg)
                                st.rerun()  
                            else:
                                st.error(msg)
                    except ValueError:
                        st.error("Please enter a valid number")


# History Tab
with tabs[2]:
    st.header("📜 Auction History")
    past_auctions = list(auctions_col.find({"active": False}).sort("end_time", -1))
    if not past_auctions:
        st.info("No past auctions.")
    else:
        for item in past_auctions:
            with st.expander(f"📦 {item['item_name']} (Base: ${item['base_price']:.2f})"):
                st.write(f"**Description:** {item['description']}")
                st.write(f"**Seller:** {item['seller']}")
                if item["highest_bidder"]:
                    bidder = users_col.find_one({"_id": ObjectId(item['highest_bidder'])})
                    st.success(f"Winner: {bidder['username']} (${item['current_highest_bid']:.2f})")
                else:
                    st.warning("No bids placed")

