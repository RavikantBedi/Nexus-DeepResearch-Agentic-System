from fpdf import FPDF
try:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(0, 10, "Testing unicode bullet: \u2022 and arrow \u2192")
    pdf.output("test.pdf")
    print("SUCCESS")
except Exception as e:
    print(f"FAILED: {e}")
