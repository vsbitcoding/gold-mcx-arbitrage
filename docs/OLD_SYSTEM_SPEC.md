# Gurukrupa Bullion — Old System (Chirayu VOTSv5) Complete Functional Spec

> Recon date: 14-Jul-2026, read-only (client-authorised). Source: live crawl of
> all ~58 admin screens (admin.gurukrupabullions.com) + 16 public pages
> (gurukrupabullions.com). This is the rebuild bible — every screen, field,
> dropdown and behaviour of the system we are replacing.

## 0. Old architecture (what we're replacing)

| Piece | Old implementation |
|---|---|
| Admin | ASP.NET WebForms + DevExpress grids + Telerik RadEditor |
| DB | SQL Server, db `VOTSv5Preview` — **multi-tenant** (GST screen shows 33 rows keyed by `miniadmin Username` = many dealers share one Chirayu install) |
| Rate distribution | Admin writes **S3 files** ("Update All S3 File", per-scrip-code files); website/app JS polls them |
| Customer login | **name + mobile + OTP** (no password); OTP via SMS gateway (DLT templates) |
| Push | FCM topic per tenant (Firebase service-account JSON uploaded in admin) + optional **AWS SNS** ("paid") |
| SMS | Gateway w/ TRAI **DLT template IDs** (OTP + order-confirm templates with placeholders) |
| WhatsApp | **Self-hosted gateway** (sender mobile + token; restart/reset/balance buttons) |
| Public site | Static HTML pages + JS; Trades/Orders pages fetch per-customer data after OTP login |
| Fragility seen live | `Set Parity` page throws a raw SQL FK error (`FK_ExpectedDeliveryMaster_LoginMiniAdmin`) on open |
| White-label artifact | Footer email is another dealer's (`info@arihantspot.com`) — shared template |

## 1. Core domain model

### 1.1 Templates (price boards)
- 3 live templates: **`gurukrupa`** (B2B), **`gurukrupab2c`** (B2C), **`gurukrupasilver`**.
- Same products, per-template parities/codes (e.g. GOLD 999 GST IMP sell parity: B2B +4950 vs B2C +2450).
- `Template Master`: add / **copy template** / delete.
- "Start All Templates" (Trades screen) = master trading on/off per template.

### 1.2 Scrip Master (per template; 45–84 rows incl. hidden)
Columns: Scrip Name | Buy Rate (manual-override input) | Buy Parity | Sell Parity |
Sell Rate (input) | Reference **Master Scrip** (Gold Spot / Silver Spot / USDINR /
GOLDAUG / SILVERSEP …) | Reference **My Scrip** (another scrip, e.g. GOLD 999 → GOLD COST) |
Visible | Allow Trade | Position | Reset Low/High | ↑↓ | Scrip Code | Delete.
Row actions: Edit, **−5/+5 nudge**, buy/sell flags, Reset H/L. Toolbar: template
dropdown, Add New Scrip, Export XLS, Hide Rows, search.
**Rate math:** `rate = reference(buy|sell) + parity`, manual value overrides.

### 1.3 Costing engines (3 flavours — all feed scrip parities)
- **Costing** (`frmCosting`): per product — radio (2 modes), Rate source
  [GOLD 1|GOLD 2], `Premium`, `Multiplier`, INR [USDINR|DINR|manual value],
  `Interbank`, Custom Duty [Self|Live + value], `GST`, MCX Rate binding
  [Gold Current|Gold Next|GOLDFEB|GOLDAPR|GOLDJUN|GOLDAUG], `Bank to MCX`,
  Ask/Bid price choice → writes the product's parity. (≡ landed-cost import
  parity formula — **identical math to our dashboard Premium tab**.)
- **Costing Refinery**: same + duty multiplier chain
  (`PremiumCustomDuty`, `MultiplieCustomDuty`, `MultiplyCurrencyCustomDuty`, `MultiplyDutyCustomDuty`).
- **Easy Premium** (`frmCosting2`): one quick **sell-parity** box per product (uc1..uc12), per template.

### 1.4 R-Panel (manual rate board override)
Two blocks — **International ("C" = spot/COMEX)** and **Domestic** — each with
editable Gold & Silver `Bid/Ask/High/Low/LTP`; plus per-product preview table
`Base Ask + Sell Diff + Tax → Sell Rate / Base Bid + Buy Diff + Tax → Buy Rate`; single **SAVE**.
Use case: drive the board manually if feeds break / special pricing.

### 1.5 Shift Contract
One-click contract roll: `Gold Current All`, `Gold Next All`, `Silver Current All`,
`Silver Next All`, explicit `SILVERJUL TO SILVERSEP`, plus `Hide all Rates` / `Show all Rates` kill-switch.

## 2. Trading & clients

| Screen | Contents |
|---|---|
| **Trade Entry** | ScripCode, ScripName, Buy/Sell, Qty, Price, Client Group, Client Code/Name/Mobile, Trade Time → Save/Cancel (dealer books on behalf of client) |
| **Trades** | Grid: Name, Scrip, B/S, Qty, Price, Time, CC (~37 rows live); date filter; **Start All Templates / Start Trading** |
| **Pending Orders** | Same columns — customer limit orders waiting for price |
| **Stock Lock Report** | Per scrip: Buy Qty in Stock, Actual Buy, Pending Buy, Buy Qty in Pending Order, Sell equivalents (position/inventory view), editable |
| **Client Details** | Client picker → profile popup (Name, Address, Status, Contact person, Mobile, Telephone, Email) + 3 date-range tabs (trades/orders/ledger) |
| **Margin (Client)** | Deposit ledger: Client Code, Margin Type, Margin Value, Entry Time, Voucher No + add form |
| **Scripwise-Clientwise Allow Trade** | Client × Scrip → is Allow Trade (48 rows), Enable All / Disable All |
| **Scripwise-Clientwise Margin** | Client × Scrip → Buy Margin, Sell Margin, Buy/Sell Min & Max Qty (43 rows) |
| **Discount Scripwise-Clientwise** | Client × Scrip → Buy/Sell Discount + min qty (28 rows) — preferential pricing |
| **List of Registration** | App signups: ID, Name, Mobile, City, Mobile Type, Entry Time + Excel export |
| **Booking Desk** | Rich-text page (contact person e.g. "Rohit Vadhel" + numbers) shown on site |

## 3. Hedging (auto-cover dealer exposure)
- **Auto Hedging** (`BullionToBullion`): rules — Source Scrip → Target Scrip,
  Limit Order Difference, **API Link + Success Response** (external broker API),
  Qty Multiplier, `isHedgeManualTrade`, per-rule enable + **Start All / Stop All**.
- **Scrip Hedging**: hedgeable scrip master (Scrip Name/Code/Type; file upload).
- **Config Hedging API**: credentials (username etc.) + Start/Stop hedging.

## 4. Notifications suite

| Channel | Screens & fields |
|---|---|
| News | Title + RadEditor rich text + image upload + **YouTube link** + location; category=NEWS; history grid |
| Ticker ×2 | Rich-text marquee (3 file uploads each) |
| Fix Message | Persistent message on Live-Rate page (save/clear) |
| Pop-Up Message | Website popup (rich text, save/clear) |
| Push (FCM v2) | Title, Message, Android/iPhone checkboxes, **Send Twice**, image, topic send; **Schedule** variant (time + weekday checkboxes); **Test** by device token; per-tenant Firebase service-account JSON upload; **AWS SNS** access key/secret/topicArn ("paid" variant) |
| SMS | Alert numbers per SMSType (grid); **SMS Setting Template**: version, mobile list, port, server number, API type, Sender ID, **DLT Template ID for OTP** + template, **DLT for Order-Confirm** + template with placeholder buttons (VendorName, Client Name, Product, Trade No, Order No, Rate, Qty, Buy/Sell, Time) |
| WhatsApp | Self-hosted gateway: **Branch Number**, Restart/Reset/Refresh, test message, **balance top-up**; Setting (mobile, PhoneSenderID, token); Templates (header/body, "Sync With Whatsapp") |
| Custom Sound | Enable checkbox (app rate-alert sound) |

## 5. App & company config
- **Gold-Silver Up-Down**: up/down difference thresholds (rate-move push triggers),
  Android/iPhone Application ID + Sender ID, Company Title, `isAllowUpDownNotification`,
  Link Name, Website/Android/iPhone links, Email, WhatsApp No, Call No, Send-to-Topic, APK download.
- **Update App**: version number, `isUpdate`, `isCompulsory`, store links, message → push.
- **Ticker Version Setting**: version + `NotAllowedPipe` + confirm message (ticker file format).
- **Ticker Update In All User**: "Update All S3 File" / "Update All Scrip Code in S3 File".
- Content pages (RadEditor): About Us, Bank Details, Expected Delivery (stock comment), Category Master.
- **Add Balance**: tenant's bank a/c + IFSC + **Generate QR / Check Payment** (pay Chirayu).
- Support Ticket (OTP-gated), Changes Request (rich-text request to vendor), Agree Log.

## 6. Users & security
- **User Right**: login TYPES (roles) + per-screen permission matrix (Add / Update / Delete / View checkboxes).
- **Sub-User Scrip Filter / Hide**: per sub-user allowed/hidden scrips (checkbox grid).
- **OTP Numbers**: up to 5 admin mobiles + emails (admin-login OTP).
- Login Log (date range), **Audit** (Scrip Template Changes, Discount Changes, Client
  Master Changes — last 50; Trades Changes — last 1000), Settings Logs, Change Password.
- Every login shows a **Software Maintenance Agreement** ("I Agree") gate + Agree Log.

## 7. Public site / customer app (gurukrupabullions.com + Play Store app)

| Page | Function |
|---|---|
| Home | Hero + LIVE board (GOLD($), INR(₹), GOLD COST with Low\|High; products with BUY/SELL + L/H), IBJA membership, products (Gold 995/999 coins 1g–50g, bars), app download |
| Live Rates | Full live board (same data, S3/JS-driven) |
| Messages | Published News items (timestamped) |
| KYC (`kyc.aspx`) | Form: Company, Client Name, Address, Name1/Name2, Mobile1/Mobile2, Office1/Office2, Email … → submit |
| Download | App links (Play Store; iPhone) |
| Gold / Silver Trend | Chart + "Entry Price" reference |
| **Login** (`www/Login.htm`) | name + mobile → **Generate OTP** → otp → login (JS/S3 backed) |
| Trades / Pending Orders | Customer's own trades & pending orders (JS after login; Symbol, B/S, Qty, Price) |
| FAQ / Contact / Booking Desk / About / Privacy | Content pages; Contact form (name/email/phone/message) |
| Open Account | Registration (feeds admin "List of Registration") |

## 8. Rebuild mapping (old → new)

| Old area | New admin module | Status / notes |
|---|---|---|
| Scrip Master (+templates, nudge, visible/trade, reorder, chaining) | **Scrip Master** | ✅ v1 LIVE at /admin/ (live feeds, 3rd template `gurukrupasilver` still to seed) |
| Costing / Easy Premium / Refinery | Costing screen | Math already exists (dashboard Premium tab); UI to build |
| R-Panel manual overrides | R-Panel screen | To build (manual override + per-product preview) |
| Shift Contract | part of Scrip Master/settings | Our feeds auto-roll contracts — mostly obsolete; keep hide/show all |
| Trades / Pending / Trade Entry / Stock Lock | Trading module | Phase 2 (orders lifecycle) |
| Client risk (allow/margin/discount) + Client Details + Margin vouchers | Clients module | Phase 2 |
| Registration + KYC | Onboarding module | Phase 2 |
| News/Ticker/Fix/Pop-up | Content module | Simple CRUD + site render |
| Push / SMS / WhatsApp | Notifications module | FCM infra exists; SMS/WhatsApp need client gateway accounts (DLT/Meta) |
| Auto Hedging | Hedging module | Phase 3 (needs broker API decision) |
| User Right / sub-users / audit | Roles & audit | Phase 2 |
| Gold-Silver UpDown / Update App / content pages | Settings module | Simple forms |
| S3 rate distribution | **WebSocket + REST** (already our stack) | Big modernisation win |
| Customer OTP login | mobile+OTP auth | Needs SMS gateway (DLT) |

## 9. Open questions for the client
1. Which of the 58 screens are actually USED? (Audit shows real use of: Scrip Master,
   Costing, Trades/Pending, client margin/discount, News/Push/Ticker, WhatsApp.)
2. Hedging: which broker API is configured today — keep in rebuild?
3. SMS + WhatsApp gateways: client opens own accounts (DLT/Meta) — old ones are Chirayu's.
4. Customer app: reuse mobile+OTP login? PWA vs native?
5. Historic data to migrate: clients, trades, ledger, registrations (needs Chirayu DB access).
