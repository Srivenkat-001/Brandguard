"""Generate the demo brand ("Veridian Bank", fictional), logos and fixture feeds.

    python scripts/make_demo_data.py

Everything here is fictional; no real brand, person or app is referenced.
"""
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "data" / "demo"
LOGOS = OUT / "logos"
LOGOS.mkdir(parents=True, exist_ok=True)


def logo(bg=(20, 40, 110), fg=(255, 255, 255), accent=(240, 190, 40), shift=(0, 0), scale=1.0):
    S = 256
    img = Image.new("RGB", (S, S), bg)
    d = ImageDraw.Draw(img)
    cx, cy = S // 2 + shift[0], S // 2 + shift[1]
    w, h = 150 * scale, 150 * scale
    d.polygon([(cx - w / 2, cy - h / 2), (cx - w / 6, cy - h / 2), (cx, cy + h / 5),
               (cx + w / 6, cy - h / 2), (cx + w / 2, cy - h / 2), (cx, cy + h / 2)], fill=fg)
    r = 16 * scale
    d.ellipse([cx + w / 2 - r, cy - h / 2 - r * 2, cx + w / 2 + r, cy - h / 2], fill=accent)
    return img


def jpeg_roundtrip(img, q=45):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=q)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def other_logo(bg=(30, 120, 70)):
    img = Image.new("RGB", (256, 256), bg)
    d = ImageDraw.Draw(img)
    d.polygon([(128, 50), (205, 200), (51, 200)], fill=(255, 255, 255))
    d.ellipse([105, 120, 151, 166], fill=(250, 200, 60))
    return img


logo().save(LOGOS / "official.png")
jpeg_roundtrip(logo(bg=(28, 48, 120), shift=(4, 3), scale=0.97)).save(LOGOS / "clone_exact.png")
jpeg_roundtrip(logo(bg=(40, 70, 150), shift=(8, 6), scale=0.92)).filter(ImageFilter.GaussianBlur(1.2)).save(LOGOS / "clone_near.png")
other_logo().save(LOGOS / "unrelated_green.png")
other_logo((200, 110, 40)).save(LOGOS / "unrelated_orange.png")

brand = {
    "name": "Veridian Bank",
    "domains": ["veridianbank.com", "veridianbank.co.in"],
    "description": ("Veridian Bank offers savings accounts, credit cards, personal loans and UPI payments. "
                    "Manage your accounts, pay bills, transfer money and track spending securely "
                    "with the official Veridian Bank mobile banking app."),
    "logo_path": "logos/official.png",
    "aliases": ["Veridian"],
    "keywords": ["mobile banking", "savings account", "credit card", "personal loan", "upi"],
    "official_accounts": [
        {"platform": "x", "handle": "VeridianBank"},
        {"platform": "instagram", "handle": "veridianbank"},
        {"platform": "facebook", "handle": "VeridianBankOfficial"},
        {"platform": "linkedin", "handle": "veridian-bank"},
    ],
    "official_apps": [
        {"store": "google_play", "app_id": "com.veridianbank.mobile", "name": "Veridian Bank Mobile"},
        {"store": "app_store", "app_id": "com.veridianbank.mobile", "name": "Veridian Bank Mobile"},
    ],
    "official_developers": [
        {"name": "Veridian Bank Ltd", "developer_id": "dev-veridian-001"},
    ],
    "allowlist": [],
}
(OUT / "brand.json").write_text(json.dumps(brand, indent=2))

social = [
    # ---- official (must be excluded) ----
    {"platform": "x", "handle": "VeridianBank", "display_name": "Veridian Bank", "type": "profile",
     "bio": "Official account of Veridian Bank. Never share OTP/PIN with anyone.", "followers": 482000,
     "account_age_days": 3900, "verified": True, "links": ["https://veridianbank.com"], "avatar": "logos/official.png"},
    {"platform": "instagram", "handle": "veridianbank", "display_name": "Veridian Bank", "type": "profile",
     "bio": "Banking made simple.", "followers": 120000, "account_age_days": 2800, "verified": True,
     "links": ["https://veridianbank.com/app"], "avatar": "logos/official.png"},
    {"platform": "facebook", "handle": "VeridianBankOfficial", "display_name": "Veridian Bank", "type": "page",
     "bio": "Official Facebook page.", "followers": 260000, "account_age_days": 3500, "verified": True,
     "links": ["https://veridianbank.com"], "avatar": "logos/official.png"},
    # ---- impersonators / scams ----
    {"platform": "x", "handle": "Veridian_Bank_Support", "display_name": "Veridian Bank Support", "type": "profile",
     "bio": "24x7 customer care. DM your account number & OTP for instant KYC update. WhatsApp +91 90000 00000",
     "followers": 312, "account_age_days": 21, "verified": False, "links": ["https://wa.me/919000000000"],
     "avatar": "logos/clone_exact.png"},
    {"platform": "instagram", "handle": "veridianbnak", "display_name": "Veridian Bank", "type": "profile",
     "bio": "GIVEAWAY! You have won Rs 25,000 Veridian rewards. Claim now, DM us.", "followers": 1450,
     "account_age_days": 40, "verified": False, "links": ["https://bit.ly/claim-veridian"],
     "avatar": "logos/clone_exact.png"},
    {"platform": "facebook", "handle": "VeridianBank.Rewards.Official", "display_name": "VeridianBank Official Rewards",
     "type": "page", "bio": "Exclusive cashback offers for Veridian customers. Verify your account to claim.",
     "followers": 2210, "account_age_days": 55, "verified": False,
     "links": ["https://veridianbank-rewards.com/login"], "avatar": "logos/clone_near.png"},
    {"platform": "telegram", "handle": "veridian_bank_helpdesk", "display_name": "Veridian Bank Helpdesk", "type": "profile",
     "bio": "Account blocked? Send your debit card number and CVV here to reactivate.", "followers": 95,
     "account_age_days": 9, "verified": False, "links": [], "avatar": "logos/unrelated_green.png"},
    {"platform": "instagram", "handle": "v\u0435ridianbank", "display_name": "V\u0435ridian Bank", "type": "profile",
     "bio": "Banking made simple.", "followers": 380, "account_age_days": 30, "verified": False,
     "links": [], "avatar": "logos/clone_near.png"},
    {"platform": "linkedin", "handle": "veri-dian-bank", "display_name": "Veri dian Bank", "type": "page",
     "bio": "Hiring: work from home, earn Rs 5,000 per day. Registration fee required.", "followers": 140,
     "account_age_days": 60, "verified": False, "links": [], "avatar": "logos/unrelated_green.png"},
    {"platform": "x", "handle": "veridian1bank", "display_name": "Veridian Bank", "type": "profile",
     "bio": "Updates and offers.", "followers": 870, "account_age_days": 75, "verified": False,
     "links": ["https://veridian-bank.co/offers"], "avatar": "logos/clone_exact.png"},
    # ---- benign: must NOT be flagged (or stay below threshold) ----
    {"platform": "facebook", "handle": "VeridianBakery", "display_name": "Veridian Bakery", "type": "page",
     "bio": "Fresh sourdough and pastries every morning.", "followers": 5200, "account_age_days": 1900,
     "verified": False, "links": ["https://veridianbakery.example"], "avatar": "logos/unrelated_orange.png"},
    {"platform": "x", "handle": "VeridianCU", "display_name": "Veridian Credit Union", "type": "profile",
     "bio": "Member-owned credit union serving Pennsylvania.", "followers": 22000, "account_age_days": 3000,
     "verified": True, "links": ["https://veridiancu.example"], "avatar": "logos/unrelated_green.png"},
    {"platform": "x", "handle": "VeridianBankFans", "display_name": "Veridian Bank Fans", "type": "profile",
     "bio": "Fan commentary on Veridian Bank news. Not affiliated.", "followers": 3400, "account_age_days": 900,
     "verified": False, "links": [], "avatar": "logos/unrelated_orange.png"},
    {"platform": "instagram", "handle": "venetianbank", "display_name": "Venetian Bank", "type": "profile",
     "bio": "Heritage banking since 1890.", "followers": 8800, "account_age_days": 2500, "verified": True,
     "links": [], "avatar": "logos/unrelated_green.png"},
    {"platform": "facebook", "handle": "veridianhikers", "display_name": "Veridian Valley Hiking Club", "type": "page",
     "bio": "Weekend trails and campfires.", "followers": 640, "account_age_days": 1200, "verified": False,
     "links": [], "avatar": "logos/unrelated_orange.png"},
]
(OUT / "social_feed.json").write_text(json.dumps(social, indent=2))

official_desc = brand["description"]
apps = [
    # ---- official (must be excluded) ----
    {"store": "google_play", "app_id": "com.veridianbank.mobile", "name": "Veridian Bank Mobile",
     "developer": "Veridian Bank Ltd", "developer_id": "dev-veridian-001", "description": official_desc,
     "installs": 5000000, "rating": 4.4, "permissions": ["INTERNET", "USE_BIOMETRIC", "CAMERA"],
     "icon": "logos/official.png"},
    {"store": "app_store", "app_id": "com.veridianbank.mobile", "name": "Veridian Bank Mobile",
     "developer": "Veridian Bank Ltd", "developer_id": "dev-veridian-001", "description": official_desc,
     "installs": None, "rating": 4.6, "permissions": [], "icon": "logos/official.png"},
    # ---- impersonators ----
    {"store": "google_play", "app_id": "com.vrdn.rewards2024", "name": "Veridian Bank Rewards",
     "developer": "Mobile Tools Studio", "developer_id": "dev-x-9981",
     "description": "Claim free Veridian Bank cashback and unlimited rewards. Login with your card number and OTP.",
     "installs": 500, "rating": 2.9,
     "permissions": ["READ_SMS", "SEND_SMS", "SYSTEM_ALERT_WINDOW", "BIND_ACCESSIBILITY_SERVICE", "INTERNET"],
     "icon": "logos/clone_exact.png"},
    {"store": "google_play", "app_id": "com.veridian.bank.mobile2", "name": "VeridianBank Mobile",
     "developer": "Appify Labs", "developer_id": "dev-x-4410", "description": official_desc.replace("official ", ""),
     "installs": 2000, "rating": 3.4, "permissions": ["INTERNET", "READ_SMS", "READ_CONTACTS"],
     "icon": "logos/clone_exact.png"},
    {"store": "google_play", "app_id": "net.verldian.app", "name": "Verldian Bank",
     "developer": "J Smith", "developer_id": "dev-x-7722",
     "description": "Mobile banking, savings account and credit card management.", "installs": 100, "rating": 0.0,
     "permissions": ["INTERNET", "REQUEST_INSTALL_PACKAGES"], "icon": "logos/clone_near.png"},
    {"store": "app_store", "app_id": "com.quickpay.vbpay", "name": "Veridian Bank - Official Pay",
     "developer": "Veridian Bank Ltd", "developer_id": "dev-x-5555",
     "description": "Pay bills and send money instantly. UPI enabled.", "installs": None, "rating": 3.0,
     "permissions": [], "icon": "logos/unrelated_green.png"},
    # ---- benign: must NOT be flagged (or stay below threshold) ----
    {"store": "google_play", "app_id": "com.veridianbakery.orders", "name": "Veridian Bakery Orders",
     "developer": "Veridian Bakery LLC", "developer_id": "dev-bk-1", "description": "Order fresh bread for pickup.",
     "installs": 10000, "rating": 4.7, "permissions": ["INTERNET"], "icon": "logos/unrelated_orange.png"},
    {"store": "google_play", "app_id": "org.openmaps.atmfinder", "name": "ATM & Branch Finder",
     "developer": "OpenMaps", "developer_id": "dev-om-2",
     "description": "Find ATMs and branches of any bank, including Veridian Bank, HDFC and others near you.",
     "installs": 800000, "rating": 4.3, "permissions": ["INTERNET", "ACCESS_FINE_LOCATION"],
     "icon": "logos/unrelated_green.png"},
    {"store": "google_play", "app_id": "com.venetianbank.app", "name": "Venetian Bank",
     "developer": "Venetian Bank SpA", "developer_id": "dev-vb-1", "description": "Heritage banking in your pocket.",
     "installs": 300000, "rating": 4.1, "permissions": ["INTERNET"], "icon": "logos/unrelated_green.png"},
]
(OUT / "app_feed.json").write_text(json.dumps(apps, indent=2))
print("Wrote demo data to", OUT)
