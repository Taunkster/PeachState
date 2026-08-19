"""PeachState CoolChain dashboard — Heat Intelligence Report viewer.

Day 5 (docs/02): embedded PDF viewer (streamlit-pdf-viewer when installed,
iframe data-URI fallback), a download button for buyers/insurers, and a
synthetic report card when the PDF fixture is missing.
"""

from __future__ import annotations

from typing import Any

import streamlit as st


def synthetic_report_card(report: dict[str, Any]) -> str:
    """Offline-safe summary card shown when the PDF is unavailable."""
    summary = report.get("summary", {})
    sections = " · ".join(summary.get("sections", []))
    return f"""
    <div class="pcs-card pcs-fade">
      <div style="font-size:16px;font-weight:700;">📄 {report.get('title', 'Heat Intelligence Report')}</div>
      <div style="font-size:13px;color:#5b5f66;margin-top:4px;">
        Region: {summary.get('region', '—')} · Activity {report.get('activity_id', '—')}
      </div>
      <div style="margin-top:8px;font-size:13px;">{summary.get('headline', '')}</div>
      <div style="margin-top:8px;font-size:12px;color:#5b5f66;">
        Sections: {sections}<br>
        Generated {report.get('generated_ts', '—')}
      </div>
    </div>
    """


def render_pdf_viewer(report: dict[str, Any]) -> bool:
    """Embed the PDF. Returns True when a real PDF was displayed."""
    pdf_bytes = report.get("pdf_bytes")
    if not pdf_bytes:
        return False

    try:
        from streamlit_pdf_viewer import pdf_viewer

        pdf_viewer(pdf_bytes, width="100%", height=720)
        return True
    except Exception:
        pass

    # iframe data-URI fallback (works fully offline).
    b64 = report.get("pdf_b64")
    if not b64:
        return False
    src = f"data:application/pdf;base64,{b64}"
    st.components.v1.html(
        f'<iframe src="{src}" width="100%" height="720" '
        f'style="border:none;border-radius:12px;"></iframe>',
        height=740,
    )
    return True


def render(st, *, report: dict[str, Any]) -> None:
    st.markdown(
        '<div style="font-size:20px;font-weight:700;">🌡 Heat Intelligence '
        'Report — Fort Valley / Peach County</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Premium FortyGuard `heat_intelligence` report — for buyers, insurers "
        "and packing-house QA. Activity "
        f"`{report.get('activity_id', '—')}` · generated "
        f"{report.get('generated_ts', '—')}"
    )

    pdf_bytes = report.get("pdf_bytes")
    if pdf_bytes:
        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            st.download_button(
                "⬇ Download PDF",
                data=pdf_bytes,
                file_name="heat_intelligence_fort_valley.pdf",
                mime="application/pdf",
                key="hi_download",
                type="primary",
            )
        with c2:
            st.metric("Pages", report.get("summary", {}).get("pages", "—"))
        with c3:
            st.metric("Sections", "5",
                      help="Geographic · Environmental · Urban · Events · Anthropogenic")

        ok = render_pdf_viewer(report)
        if not ok:
            st.markdown(synthetic_report_card(report), unsafe_allow_html=True)
    else:
        st.warning("PDF fixture not found — showing the synthetic report summary.")
        st.markdown(synthetic_report_card(report), unsafe_allow_html=True)


__all__ = ["synthetic_report_card", "render_pdf_viewer", "render"]