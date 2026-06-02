"""Create 3 small sample PDFs for a quick local demo."""

from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def write_pdf(filename: str, title: str, paragraphs: list[str]) -> None:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", style="B", size=16)
    pdf.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", size=11)
    for p in paragraphs:
        pdf.multi_cell(0, 6, p)
        pdf.ln(2)
    DOCS.mkdir(parents=True, exist_ok=True)
    pdf.output(DOCS / filename)


def main() -> None:
    write_pdf(
        "deployment-guide.pdf",
        "Deployment Guide",
        [
            "This guide describes how to deploy the Payment Service to staging and production.",
            "Prerequisites: Kubernetes 1.28+, Helm 3.14+, and access to the eng-deploy namespace.",
            "Staging rollout: run helm upgrade payment-service ./charts/payment -f values-staging.yaml. "
            "Verify health at /healthz before promoting.",
            "Production rollout requires change ticket CHG-1001 and two approvers from SRE.",
            "Rollback: helm rollback payment-service <revision> within 30 minutes of a failed deploy.",
        ],
    )

    write_pdf(
        "api-security.pdf",
        "API Security",
        [
            "All public APIs must use OAuth 2.0 client credentials for machine-to-machine access.",
            "Human-facing apps use OpenID Connect with PKCE via the corporate identity provider.",
            "JWT access tokens expire after 15 minutes. Refresh tokens are not issued for service accounts.",
            "Rate limiting: 1000 requests per minute per client_id at the API gateway.",
            "Sensitive fields (PAN, CVV) must never appear in logs or error messages.",
        ],
    )

    write_pdf(
        "architecture-overview.pdf",
        "Architecture Overview",
        [
            "The platform consists of: API Gateway, Auth Service, Payment Service, and Notification Service.",
            "Payment Service owns card capture and settlement; it stores no raw card data (tokenization only).",
            "Notification Service consumes events from the payment.events Kafka topic.",
            "Shared libraries live in the platform-commons repository; version with semantic release tags.",
            "Observability: OpenTelemetry traces, Prometheus metrics, Grafana dashboards per service.",
        ],
    )

    print(f"Created 3 sample PDFs in {DOCS}")


if __name__ == "__main__":
    main()
