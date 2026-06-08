from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Optional
import fitz
import httpx
import base64
import io
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")

ON_STATES = {
    "checkbox_11dhbi": "Yes_xztj", "checkbox_12mxin": "Yes_gkkx",
    "checkbox_13lguc": "Yes_solw", "checkbox_14aihh": "Yes_kglf",
    "checkbox_15kdda": "Yes_mukk", "checkbox_16rxtt": "Yes_snix",
    "checkbox_17pokc": "Yes_ulxf", "checkbox_18zykc": "Yes_sweb",
    "checkbox_19pkch": "Yes_eniv", "checkbox_20ifmi": "Yes_yprc",
}

TEXT_FIELDS = [
    "text_1ejgt","text_10wjbm","text_2gzhq","text_9efrs",
    "text_3lqed","text_8otdl","text_4hrdg","text_7glwo",
    "text_5lwvy","text_6vupi","text_23ceve","text_24qwgq",
    "text_25ylid","textarea_21gqqm","textarea_22yjpn",
]

class FillRequest(BaseModel):
    fields: Dict[str, str]

class EmailRequest(BaseModel):
    to_email: str
    subject: str
    html_body: str

@app.get("/")
def health():
    return {"status": "ok", "pymupdf": fitz.version[1]}

@app.post("/fill-pdf")
async def fill_pdf(req: FillRequest):
    fields = req.fields

    # Pick PDF based on effective character count (newlines cost extra)
    repair_text = fields.get("textarea_21gqqm", "")
    details_text = fields.get("textarea_22yjpn", "")
    repair_cost = len(repair_text) + (repair_text.count("\n") * 60)
    details_cost = len(details_text) + (details_text.count("\n") * 122)

    # Use smaller font PDF if text is long
    if repair_cost > 848 or details_cost > 2029:
        pdf_name = "findings-blank-8pt.pdf"
    elif repair_cost > 598 or details_cost > 1628:
        pdf_name = "findings-blank-9pt.pdf"
    else:
        pdf_name = "findings-blank.pdf"

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SUPABASE_URL}/storage/v1/object/docs/{pdf_name}",
            headers={"Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"},
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Could not fetch blank PDF {pdf_name}: {resp.status_code}")
        pdf_bytes = resp.content

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]

    checkbox_rects = {}
    for w in page.widgets():
        if w.field_name in ON_STATES:
            checkbox_rects[w.field_name] = fitz.Rect(w.rect)

    for w in page.widgets():
        name = w.field_name
        if name in TEXT_FIELDS:
            w.field_value = fields.get(name, "")
            w.text_fontsize = 11
            w.update()

    DARK = (0.1, 0.15, 0.35)
    for name, rect in checkbox_rects.items():
        if fields.get(name) == "Yes":
            cx = (rect.x0 + rect.x1) / 2
            cy = (rect.y0 + rect.y1) / 2
            r = min(rect.width, rect.height) * 0.35
            p1 = fitz.Point(cx - r, cy)
            p2 = fitz.Point(cx - r*0.1, cy + r*0.9)
            p3 = fitz.Point(cx + r*1.1, cy - r*0.8)
            page.draw_line(p1, p2, color=DARK, width=1.8)
            page.draw_line(p2, p3, color=DARK, width=1.8)

    for w in [w for w in page.widgets() if w.field_name in ON_STATES]:
        page.delete_widget(w)

    buf = io.BytesIO()
    doc.save(buf, garbage=4, deflate=True)
    doc.close()
    buf.seek(0)

    reader = PdfReader(buf)
    writer = PdfWriter()
    writer.append(reader)

    page_w = writer.pages[0]
    for annot_ref in page_w.get('/Annots', []):
        annot = annot_ref.get_object()
        parent = annot.get('/Parent', {})
        if hasattr(parent, 'get_object'): parent = parent.get_object()
        if str(parent.get('/FT', '')) == '/Tx':
            current_ff = int(str(parent.get('/Ff', 0)))
            parent[NameObject('/Ff')] = NumberObject(current_ff | 1)

    out_buf = io.BytesIO()
    writer.write(out_buf)

    b64 = base64.b64encode(out_buf.getvalue()).decode()
    return {"pdf_b64": b64}

@app.post("/send-email")
async def send_email(req: EmailRequest):
    if not SMTP_USER or not SMTP_PASS:
        raise HTTPException(status_code=500, detail="SMTP credentials not configured")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = req.subject
    msg["From"] = f"Trusight <{SMTP_USER}>"
    msg["To"] = req.to_email
    msg.attach(MIMEText(req.html_body, "html"))

    # Python's smtplib works reliably with Gmail app passwords
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, req.to_email, msg.as_string())

    return {"sent": True, "to": req.to_email}
