from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict
import fitz
import httpx
import base64
import io
import os
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

def set_readonly_recursive(field_ref):
    field = field_ref.get_object() if hasattr(field_ref, 'get_object') else field_ref
    current_ff = int(str(field.get('/Ff', 0)))
    field[NameObject('/Ff')] = NumberObject(current_ff | 1)
    for kid in field.get('/Kids', []):
        set_readonly_recursive(kid)

@app.get("/")
def health():
    return {"status": "ok", "pymupdf": fitz.version[1]}

@app.post("/fill-pdf")
async def fill_pdf(req: FillRequest):
    fields = req.fields

    # Download blank PDF from Supabase Storage
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SUPABASE_URL}/storage/v1/object/docs/findings-blank.pdf",
            headers={"Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"},
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Could not fetch blank PDF: {resp.status_code}")
        pdf_bytes = resp.content

    # Step 1: Fill with pymupdf (generates proper appearance streams)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]

    for w in page.widgets():
        name = w.field_name
        if name in TEXT_FIELDS:
            w.field_value = fields.get(name, "")
            w.text_fontsize = 11
            w.update()
        elif name in ON_STATES:
            w.field_value = ON_STATES[name] if fields.get(name) == "Yes" else "Off"
            w.update()

    # Use bake() if available (pymupdf >= 1.24.2), otherwise save normally
    if hasattr(doc, 'bake'):
        doc.bake()
        out_bytes = doc.tobytes(garbage=4, deflate=True)
        doc.close()
    else:
        buf = io.BytesIO()
        doc.save(buf, garbage=4, deflate=True)
        doc.close()
        buf.seek(0)

        # Step 2: Set all fields ReadOnly using pypdf
        reader = PdfReader(buf)
        writer = PdfWriter()
        writer.append(reader)

        acroform = writer._root_object.get('/AcroForm', {})
        if hasattr(acroform, 'get_object'):
            acroform = acroform.get_object()
        for field_ref in acroform.get('/Fields', []):
            set_readonly_recursive(field_ref)

        out_buf = io.BytesIO()
        writer.write(out_buf)
        out_bytes = out_buf.getvalue()

    b64 = base64.b64encode(out_bytes).decode()
    return {"pdf_b64": b64}
