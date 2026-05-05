# Sample WorkIQ Documents

These files simulate the organizational data that Microsoft WorkIQ would surface from M365 (Outlook, Teams, SharePoint, OneDrive) during a hybrid AI demo.

In a real deployment, this data lives in your M365 tenant and is accessed securely via WorkIQ. For demo purposes, these documents show what the experience looks like without requiring a live M365 connection.

## Files

| Document | Simulates | Source System |
|----------|-----------|---------------|
| `fnol_call_transcript.md` | First Notice of Loss call recording transcript | Teams Phone / Call Recording |
| `claim_ticket.md` | CRM ticket with full lifecycle timeline | Dynamics 365 / CRM |
| `adjuster_field_report.md` | Field inspection report with photos log | SharePoint / Claims Portal |
| `teams_chat_history.md` | Internal Teams messages between adjuster & supervisor | Microsoft Teams |
| `email_thread_customer.md` | Email correspondence with the customer | Outlook |
| `vendor_estimate.md` | Contractor repair estimate shared via email | Outlook Attachment |
| `coverage_verification.md` | Automated coverage check from policy system | SharePoint / Policy Admin |
| `supervisor_approval_memo.md` | Internal approval workflow document | SharePoint / Power Automate |

## How It Works in the Demo

1. **WorkIQ toggle OFF** → App uses NPU-only inference (fully offline)
2. **WorkIQ toggle ON** → App enriches NPU responses with this contextual data
3. AI reasoning always happens **locally on the NPU** — only organizational context flows in

## Scenario

**Customer:** Sarah Mitchell  
**Policy:** ZAV-HO3-2024-08847  
**Claim:** CLM-2024-09283 (Water damage — basement flooding)  
**Filed:** May 2, 2024  
**Cause:** Severe storm + sump pump failure + window well overflow  
**Safety concern:** Electrical outlet near standing water  
