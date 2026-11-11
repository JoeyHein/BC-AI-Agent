"""
Email Monitoring Service for BC AI Agent
Monitors inboxes, parses emails with AI, and stores quote requests
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from fastapi import HTTPException

from app.integrations.email.client import graph_client
from app.integrations.ai.client import ai_client
from app.db.database import SessionLocal
from app.db.models import EmailLog, QuoteRequest, AIDecision, QuoteItem, BCCustomer
from app.config import settings
from app.services.memory_service import get_memory_service

logger = logging.getLogger(__name__)


class EmailMonitorService:
    """Service for monitoring emails and processing quote requests"""

    def __init__(self):
        self.graph_client = graph_client
        self.ai_client = ai_client
        # Legacy fallback for backward compatibility - supports unlimited EMAIL_INBOX_* variables
        self.legacy_inboxes = []
        for i in range(1, 11):  # Support up to 10 legacy inboxes (EMAIL_INBOX_1 through EMAIL_INBOX_10)
            inbox = getattr(settings, f'EMAIL_INBOX_{i}', None)
            if inbox:
                self.legacy_inboxes.append(inbox)

    def _get_email_connections(self, db) -> List[Dict[str, Any]]:
        """Get active email connections from database"""
        from app.db.models import EmailConnection

        connections = db.query(EmailConnection).filter(
            EmailConnection.is_active == True
        ).all()

        return [{
            'id': conn.id,
            'email_address': conn.email_address,
            'access_token': conn.access_token,
            'refresh_token': conn.refresh_token,
            'token_expires_at': conn.token_expires_at
        } for conn in connections]

    def monitor_inboxes(self, hours_back: int = 24, max_emails_per_inbox: int = 50) -> Dict[str, Any]:
        """Monitor all configured inboxes for new emails

        Args:
            hours_back: How many hours back to check for emails
            max_emails_per_inbox: Maximum emails to process per inbox

        Returns:
            Dict with processing summary
        """
        logger.info(f"Starting email monitoring cycle - checking last {hours_back} hours")

        results = {
            "total_emails_checked": 0,
            "new_emails_found": 0,
            "quote_requests_parsed": 0,
            "errors": 0,
            "by_inbox": {}
        }

        # Get email connections from database
        db = SessionLocal()
        try:
            connections = self._get_email_connections(db)

            # If no database connections, fall back to legacy settings
            if not connections:
                logger.info("No database email connections found, using legacy settings")
                for inbox_email in self.legacy_inboxes:
                    if not inbox_email:
                        continue

                    logger.info(f"Checking inbox (legacy): {inbox_email}")

                    try:
                        inbox_results = self._process_inbox(inbox_email, hours_back, max_emails_per_inbox)
                        results["by_inbox"][inbox_email] = inbox_results
                        results["total_emails_checked"] += inbox_results["emails_checked"]
                        results["new_emails_found"] += inbox_results["new_emails"]
                        results["quote_requests_parsed"] += inbox_results["quotes_parsed"]
                        results["errors"] += inbox_results["errors"]

                    except Exception as e:
                        logger.error(f"Error processing inbox {inbox_email}: {e}")
                        results["errors"] += 1
                        results["by_inbox"][inbox_email] = {"error": str(e)}
            else:
                # Use database connections
                logger.info(f"Found {len(connections)} active email connections")
                for conn in connections:
                    inbox_email = conn['email_address']
                    logger.info(f"Checking inbox: {inbox_email}")

                    try:
                        inbox_results = self._process_inbox(inbox_email, hours_back, max_emails_per_inbox)
                        results["by_inbox"][inbox_email] = inbox_results
                        results["total_emails_checked"] += inbox_results["emails_checked"]
                        results["new_emails_found"] += inbox_results["new_emails"]
                        results["quote_requests_parsed"] += inbox_results["quotes_parsed"]
                        results["errors"] += inbox_results["errors"]

                        # Update last_checked_at
                        from app.db.models import EmailConnection
                        db_conn = db.query(EmailConnection).filter(
                            EmailConnection.id == conn['id']
                        ).first()
                        if db_conn:
                            db_conn.last_checked_at = datetime.utcnow()
                            db_conn.last_sync_status = "success"
                            db.commit()

                    except Exception as e:
                        logger.error(f"Error processing inbox {inbox_email}: {e}")
                        results["errors"] += 1
                        results["by_inbox"][inbox_email] = {"error": str(e)}

                        # Update error status
                        from app.db.models import EmailConnection
                        db_conn = db.query(EmailConnection).filter(
                            EmailConnection.id == conn['id']
                        ).first()
                        if db_conn:
                            db_conn.last_sync_status = "error"
                            db.commit()

        finally:
            db.close()

        logger.info(f"Monitoring cycle complete. Found {results['new_emails_found']} new emails, "
                   f"parsed {results['quote_requests_parsed']} quote requests")

        return results

    def _process_inbox(self, inbox_email: str, hours_back: int, max_emails: int) -> Dict[str, Any]:
        """Process emails from a single inbox"""
        results = {
            "emails_checked": 0,
            "new_emails": 0,
            "quotes_parsed": 0,
            "modifications_parsed": 0,
            "errors": 0
        }

        # Get recent emails
        try:
            emails = self.graph_client.get_recent_emails(inbox_email, hours=hours_back, max_count=max_emails)
            results["emails_checked"] = len(emails)
            logger.info(f"Found {len(emails)} emails in {inbox_email}")

        except Exception as e:
            logger.error(f"Failed to retrieve emails from {inbox_email}: {e}")
            results["errors"] += 1
            return results

        # Process each email
        db = SessionLocal()
        try:
            for email in emails:
                try:
                    processed = self._process_single_email(db, email, inbox_email)
                    if processed:
                        results["new_emails"] += 1
                        if processed == "quote_request":
                            results["quotes_parsed"] += 1
                        elif processed == "quote_modification":
                            results["modifications_parsed"] += 1
                except Exception as e:
                    logger.error(f"Error processing email {email.get('id')}: {e}")
                    results["errors"] += 1

            db.commit()

        finally:
            db.close()

        return results

    def _process_single_email(self, db, email: Dict[str, Any], inbox_email: str) -> Optional[str]:
        """Process a single email

        Returns:
            "quote_request" if email was a new quote request
            "quote_modification" if email was modifying an existing quote
            "other" if email was logged but not a quote request
            None if email was already processed
        """
        message_id = email.get("id")
        internet_message_id = email.get("internetMessageId")

        # Check if already processed — use DB-level insert guard to prevent
        # duplicate AI calls from concurrent workers / scheduler instances.
        existing = db.query(EmailLog).filter(
            EmailLog.message_id == internet_message_id
        ).first()

        if existing:
            logger.debug(f"Email {internet_message_id} already processed, skipping")
            return None

        # Claim this email BEFORE calling AI — insert a placeholder row so
        # concurrent workers see it and skip. This prevents the TOCTOU race
        # where multiple workers all see "not processed" and each call the API.
        received_raw = email.get("receivedDateTime")
        try:
            received_at = datetime.fromisoformat(received_raw.replace("Z", "+00:00")) if received_raw else datetime.utcnow()
        except (AttributeError, ValueError):
            received_at = datetime.utcnow()
        placeholder = EmailLog(
            message_id=internet_message_id,
            received_at=received_at,
            from_address=email.get("from", {}).get("emailAddress", {}).get("address", ""),
            subject=email.get("subject", ""),
            body=email.get("body", {}).get("content", ""),
            status="processing",
        )
        try:
            db.add(placeholder)
            db.flush()  # attempt INSERT — will fail on duplicate key if another worker claimed it
        except Exception:
            db.rollback()
            logger.debug(f"Email {internet_message_id} claimed by another worker, skipping")
            return None

        # Extract email data
        from_address = email.get("from", {}).get("emailAddress", {}).get("address", "")
        from_name = email.get("from", {}).get("emailAddress", {}).get("name", from_address)
        subject = email.get("subject", "")
        from app.services.email_text import html_to_text
        body = html_to_text(email.get("body", {}).get("content", "") or "")

        logger.info(f"Processing new email from {from_name}: {subject[:50]}")

        attachment_mode, parse_body, pack = self._prepare_attachments(db, email, inbox_email, body)
        text_for_ai = parse_body if attachment_mode == "on" else body

        # Step 1: Categorize email with learning system
        from app.services.email_categorization_service import get_categorization_service
        categorization_service = get_categorization_service(db)

        category_result = categorization_service.categorize_email(subject, text_for_ai, from_address)

        category = category_result.get("category", "unknown")
        confidence = category_result.get("confidence", 0.0)
        reasoning = category_result.get("reasoning", "")
        is_quote_request = category == "quote_request"
        is_quote_modification = category == "quote_modification" or category_result.get("is_modification", False)
        referenced_quote_number = category_result.get("referenced_quote_number")
        modification_type = category_result.get("modification_type")

        logger.info(f"  -> Categorized as '{category}' (confidence: {confidence:.2f})")
        if reasoning:
            logger.debug(f"  -> Reasoning: {reasoning[:100]}")

        # Step 2: Update placeholder with AI categorization results
        email_log = placeholder
        email_log.status = "pending" if (is_quote_request or is_quote_modification) else "informational"
        email_log.ai_category = category
        email_log.ai_category_confidence = confidence
        email_log.ai_category_reasoning = reasoning
        email_log.is_modification = is_quote_modification
        email_log.referenced_quote_number = referenced_quote_number
        email_log.modification_type = modification_type
        if attachment_mode == "on" and pack is not None:
            email_log.attachments = pack.as_email_log()
        db.flush()

        from app.services.inbox_settings import CUSTOMER_APPROVAL, inbox_mode
        from app.services.quote_followup import (
            approval_level,
            contains_new_quote_ask,
            handle_customer_approval,
            note_also_new_request,
            note_low_approval,
        )
        approval_mode = inbox_mode(db, CUSTOMER_APPROVAL)
        approval_text = parse_body if pack is not None and approval_mode == "on" else body
        level = "none"
        if approval_mode != "off":
            try:
                level = approval_level(category, subject, approval_text)
            except Exception:
                logger.exception("Approval check failed. The message continues.")
                level = "none"
        from app.services.quote_followup import approval_exception, sizes_on_matched_quotes
        exception_text = approval_exception(approval_text) if level == "partial" else None
        referenced_sizes = None
        if level == "high" and approval_mode == "on":
            try:
                referenced_sizes = sizes_on_matched_quotes(
                    db, approval_text, from_address, subject, email_log.id,
                )
            except Exception:
                logger.exception("Could not read the quoted sizes. A repeated size will not start a new quote.")
                referenced_sizes = None
        # Shadow only logs. It must not send a go-ahead-plus-size email to the parser.
        also_new = (
            level == "high"
            and approval_mode == "on"
            and contains_new_quote_ask(subject, approval_text, referenced_sizes)
        )
        if level == "partial" and approval_mode == "shadow":
            try:
                note_low_approval(email_log, exception_text or approval_text)
            except Exception:
                logger.exception("Could not note the partial approval. The message continues.")
        elif level == "partial" and approval_mode == "on":
            try:
                row = handle_customer_approval(
                    db,
                    email_log,
                    subject=subject,
                    body=approval_text,
                    from_address=from_address,
                    graph_message_id=message_id,
                    mailbox=inbox_email,
                    filenames=[page.file_name for page in pack.pages] if pack is not None else [],
                    confidence="partial",
                    exception_text=exception_text,
                )
                email_log.status = "informational"
                db.commit()
                return "customer_approval"
            except Exception:
                logger.exception("Partial approval failed. The message continues.")
        elif level == "low":
            try:
                note_low_approval(email_log, approval_text)
            except Exception:
                logger.exception("Could not note the low-confidence approval. The message continues.")
        elif level == "high" and approval_mode == "shadow":
            nested = None
            try:
                nested = db.begin_nested()
                filenames = [page.file_name for page in pack.pages] if pack is not None else []
                handle_customer_approval(
                    db,
                    email_log,
                    subject=subject,
                    body=approval_text,
                    from_address=from_address,
                    graph_message_id=message_id,
                    mailbox=inbox_email,
                    filenames=filenames,
                )
                nested.commit()
                logger.info("  -> Approval shadow logged. The message continues on the normal path.")
            except Exception:
                logger.exception("Approval shadow failed. The message continues.")
                if nested is not None:
                    try:
                        nested.rollback()
                    except Exception:
                        pass
        elif level == "high" and approval_mode == "on":
            filenames = [page.file_name for page in pack.pages] if pack is not None else []
            approval_row = handle_customer_approval(
                db,
                email_log,
                subject=subject,
                body=approval_text,
                from_address=from_address,
                graph_message_id=message_id,
                mailbox=inbox_email,
                filenames=filenames,
            )
            if also_new:
                if approval_row is not None:
                    note_also_new_request(approval_row)
                is_quote_request = True
            else:
                email_log.status = "informational"
                db.commit()
                return "customer_approval"
        elif category == "order_confirmation" and approval_mode == "off":
            logger.info("  -> Categorized as 'order_confirmation', not processing further")
            return "other"

        # Step 3: If quote request or modification, parse with AI
        if is_quote_request:
            logger.info(f"  -> Identified as NEW quote request, parsing...")
            try:
                self._parse_quote_request(
                    db, email_log, subject, text_for_ai, from_name, from_address,
                    attachment_pack=pack if attachment_mode != "off" else None,
                    attachment_applied=attachment_mode == "on",
                    graph_message_id=message_id,
                    mailbox=inbox_email,
                )
            except Exception as e:
                logger.error(f"  -> _parse_quote_request FAILED: {e}", exc_info=True)
                email_log.status = "parse_error"
            return "quote_request"

        if is_quote_modification:
            logger.info(f"  -> Identified as QUOTE MODIFICATION (ref: {referenced_quote_number}), parsing...")
            self._parse_quote_modification(
                db, email_log, subject, body, from_name, from_address,
                referenced_quote_number, modification_type
            )
            return "quote_modification"

        logger.info(f"  -> Categorized as '{category}', not processing further")
        return "other"

    def _prepare_attachments(self, db, email, inbox_email: str, body: str):
        """Read attachments when a switch is on or in shadow. Off does not call Graph."""
        from app.services.attachment_text import MAX_FILE_BYTES, read_graph_attachments
        from app.services.inbox_settings import ATTACHMENT_READING, CUSTOMER_APPROVAL, inbox_mode

        read_mode = inbox_mode(db, ATTACHMENT_READING)
        approval_mode = inbox_mode(db, CUSTOMER_APPROVAL)
        if read_mode == "off" and approval_mode == "off":
            return read_mode, body, None
        graph_id = email.get("id")
        if not graph_id:
            return read_mode, body, None
        try:
            raw = self.graph_client.get_message_attachments(
                inbox_email, graph_id, cap_bytes=MAX_FILE_BYTES,
            )
        except Exception:
            logger.exception("Could not read attachments for %s", graph_id)
            raw = []
        pack = read_graph_attachments(raw)
        logger.info(
            "Attachments mode=%s files=%s openings=%s",
            read_mode,
            len({page.file_name for page in pack.pages}),
            len(pack.openings),
        )
        parse_body = body
        if read_mode == "on" and pack.combined_text:
            parse_body = f"{body}\n\n{pack.combined_text}"
        elif read_mode == "shadow":
            logger.info(
                "Attachment shadow would add %s opening(s) from %s. The parser still sees the message body.",
                len(pack.openings),
                ", ".join(sorted({page.file_name for page in pack.pages})) or "no files",
            )
        return read_mode, parse_body, pack

    def _remember_mail(self, parsed_data, pack, applied, graph_message_id, mailbox, record_mail=False):
        data = dict(parsed_data or {})
        if record_mail and (graph_message_id or mailbox):
            data["mail"] = {"graph_message_id": graph_message_id, "mailbox": mailbox}
        if pack is not None:
            data["attachments_read"] = pack.staff_payload(applied)
        return data

    def _settle_followups(self, db, quote, email_log, mailbox, graph_message_id):
        """Draft a follow-up. A failure here must not undo a quote already saved."""
        from app.services.quote_followup import settle_quote_followups
        nested = None
        try:
            nested = db.begin_nested()
            settle_quote_followups(
                db, quote, email_log, mailbox=mailbox, graph_message_id=graph_message_id,
            )
            nested.commit()
        except Exception:
            logger.exception(
                "Follow-up draft failed for quote %s. The quote status was kept.",
                getattr(quote, "id", None),
            )
            if nested is not None:
                try:
                    nested.rollback()
                except Exception:
                    pass

    def _parse_quote_request(self, db, email_log: EmailLog, subject: str, body: str,
                            from_name: str, from_address: str,
                            attachment_pack=None, attachment_applied=False,
                            graph_message_id=None, mailbox=None):
        """Parse quote request with AI and store in database"""

        sender_info = {"name": from_name, "email": from_address}

        # MEMORY SYSTEM: Retrieve similar examples for RAG (non-critical — continue without if it fails)
        example_context = None
        try:
            memory_service = get_memory_service(db)
            examples = memory_service.retrieve_similar_examples(
                subject, body, max_examples=3, customer_email=from_address
            )
            example_context = memory_service.format_examples_for_prompt(examples)

            customer_context = memory_service.get_customer_context(from_address)
            if customer_context:
                example_context = (example_context or "") + customer_context
                logger.info(f"  -> Known customer, using preferences for parsing")

            logger.info(f"  -> Using {len(examples)} examples for enhanced parsing")
        except Exception as e:
            logger.warning(f"  -> Memory/example retrieval failed (continuing without): {e}")

        # Parse with Claude AI (with RAG context if available)
        parse_result = self.ai_client.parse_email_for_quote(
            subject, body, sender_info, example_context=example_context
        )

        if not parse_result.get("success"):
            logger.error(f"Failed to parse quote request: {parse_result.get('error')}")
            email_log.status = "error"
            return

        from app.services.inbox_settings import inbox_modes
        record_mail = any(mode != "off" for mode in inbox_modes(db).values())
        parsed_data = self._remember_mail(
            parse_result.get("data", {}),
            attachment_pack,
            attachment_applied,
            graph_message_id,
            mailbox,
            record_mail=record_mail,
        )
        raw_confidence = parse_result.get("confidence", 0.0)

        # Extract customer info and doors for calibration
        customer = parsed_data.get("customer", {})
        doors = parsed_data.get("doors", [])
        project = parsed_data.get("project", {})

        # CONFIDENCE CALIBRATION: Adjust based on historical performance (non-critical)
        confidence = raw_confidence
        try:
            door_model = doors[0].get("model") if doors else None
            calibrated = memory_service.get_calibrated_confidence(
                raw_confidence,
                door_model=door_model,
                customer_email=from_address
            )
            if calibrated != raw_confidence:
                confidence = calibrated
                logger.info(f"  -> Confidence calibrated: {raw_confidence:.2f} -> {confidence:.2f}")
        except Exception as cal_err:
            logger.warning(f"  -> Confidence calibration failed (using raw): {cal_err}")
            db.rollback()  # Clear aborted transaction so subsequent DB ops work

        # Create QuoteRequest record
        quote_request = QuoteRequest(
            email_id=email_log.id,
            customer_name=customer.get("company_name") or customer.get("contact_name"),
            contact_email=customer.get("email") or from_address,
            contact_phone=customer.get("phone"),
            door_specs={"doors": doors} if doors else None,
            parsed_data=parsed_data,
            confidence_scores={
                "overall": confidence,
                "customer": customer.get("confidence", 0.0),
                "project": project.get("confidence", 0.0)
            },
            status="pending" if confidence >= 0.7 else "low_confidence",
            created_at=datetime.utcnow()
        )
        db.add(quote_request)
        db.flush()  # Get the ID

        # Record AI decision for audit trail
        ai_decision = AIDecision(
            quote_request_id=quote_request.id,
            decision_type="email_parse",
            input_data={"subject": subject, "body_preview": body[:500]},
            output_data=parsed_data,
            confidence_score=confidence,
            model_used=parse_result.get("model", settings.ANTHROPIC_MODEL),
            prompt_tokens=parse_result.get("tokens", {}).get("input", 0),
            completion_tokens=parse_result.get("tokens", {}).get("output", 0),
            created_at=datetime.utcnow()
        )
        db.add(ai_decision)

        # Update email log
        email_log.status = "parsed"
        email_log.parsed_at = datetime.utcnow()

        # COMMIT critical data before non-critical steps.
        # QuoteRequest + AIDecision + email status must persist even if
        # the example library or auto-generation steps fail.
        try:
            db.commit()
        except Exception as commit_err:
            logger.error(f"  -> Failed to commit QuoteRequest: {commit_err}")
            db.rollback()
            return

        # MEMORY SYSTEM: Auto-add high-confidence parses to example library (non-critical)
        if confidence >= 0.8:
            try:
                memory_service._add_to_example_library(
                    quote_request, email_log, verified=False, quality_boost=0.1
                )
                logger.info(f"  -> Auto-added to example library (high confidence)")
            except Exception as e:
                logger.warning(f"Failed to add to example library: {e}")
                try:
                    db.rollback()
                except Exception:
                    pass

        logger.info(f"  -> Quote request parsed. Confidence: {confidence:.2f}, "
                   f"Customer: {quote_request.customer_name}, "
                   f"Doors: {len(doors)}")

        # AUTO-GENERATE QUOTE via the door CONFIGURATOR — the single source of
        # truth for parts, line ordering, and BC SalesPriceLists pricing. This
        # replaces the legacy QuoteGenerationService margin-pricing path so an
        # emailed RFQ produces the exact same quote the interactive
        # configurator would for the same door.
        if confidence >= 0.7 and doors:  # Only auto-generate for reasonable confidence with doors
            try:
                logger.info(f"  -> Mapping email to configurator schema for request {quote_request.id}")
                mapping = self.ai_client.map_email_to_configurator(parsed_data, subject, body)
                request_kind = mapping.get("request_kind", "unknown")

                if not mapping.get("success"):
                    logger.warning(f"  -> Configurator mapping failed ({mapping.get('error')}); manual review")
                    quote_request.status = "needs_manual_review"
                    self._settle_followups(db, quote_request, email_log, mailbox, graph_message_id)
                    db.commit()
                    return

                # Persist the mapping for the review UI / audit regardless of path.
                quote_request.parsed_data = {**parsed_data, "configurator_mapping": mapping}

                if request_kind == "parts_request":
                    # Replacement parts (panels, sections, springs) have no
                    # portal costing yet — never guess a price. Route to a human.
                    logger.info("  -> Classified as parts/replacement request; routing to manual pricing")
                    quote_request.status = "needs_manual_pricing"
                    db.commit()
                    return

                mapped_doors = mapping.get("doors", [])
                if not mapped_doors or any(
                    (d.get("doorWidth", 0) or 0) <= 0 or (d.get("doorHeight", 0) or 0) <= 0
                    for d in mapped_doors
                ):
                    logger.info("  -> Mapped doors missing dimensions; routing to manual review")
                    quote_request.status = "needs_manual_review"
                    self._settle_followups(db, quote_request, email_log, mailbox, graph_message_id)
                    db.commit()
                    return

                # Lazy import avoids any api<->service import cycle at module load.
                from app.api.door_configurator import (
                    build_bc_quote_from_doors,
                    QuoteGenerationRequest,
                    DoorConfigRequest,
                )
                from app.services.customer_profile_service import (
                    apply_profile_for_customer,
                    merge_part_deviations,
                    quote_email_text,
                    quoting_mode,
                )

                # off keeps the old path: exact email or company name, and
                # delivery. shadow records what the profile would have done
                # and still builds that old quote. on uses the profile.
                mode = quoting_mode(db)
                live_doors = [dict(door) for door in mapped_doors]
                live_delivery = "delivery"
                delivery_explicit = False
                profile_applied = False
                customer_id = self._legacy_bc_customer_id(db, quote_request)
                if mode != "off":
                    try:
                        match = self._match_bc_customer(db, quote_request)
                        legacy_id = customer_id
                        profile_customer_id = match.bc_customer_id if match.confident else None
                        profile_apply = apply_profile_for_customer(
                            db,
                            profile_customer_id,
                            [dict(door) for door in mapped_doors],
                            delivery_type="delivery",
                            email_text=quote_email_text(
                                subject, body, getattr(email_log, "attachments", None),
                            ),
                            parsed_doors=doors,
                            explicit_fields=[[] for _ in mapped_doors],
                            explicit_complete=True,
                            customer_name=quote_request.customer_name,
                        )
                        quote_request.customer_match = {**match.as_dict(), "mode": mode}
                        quote_request.field_sources = {
                            **profile_apply["field_sources"],
                            "mode": mode,
                        }
                        quote_request.deviations = profile_apply["deviations"]
                        logger.info(
                            "Customer profile quoting mode=%s match=%s delivery=%s deviations=%s",
                            mode, match.method, profile_apply["delivery_type"],
                            len(profile_apply["deviations"]),
                        )
                        if mode == "shadow":
                            customer_id = legacy_id
                            profile_applied = True
                            if profile_apply.get("hold_for_review"):
                                quote_request.field_sources = {
                                    **(quote_request.field_sources or {}),
                                    "would_hold": True,
                                }
                            logger.info(
                                "Shadow profile left the live quote unchanged (would_hold=%s)",
                                bool(profile_apply.get("hold_for_review")),
                            )
                        elif getattr(match, "suggested", False) and not match.confident:
                            quote_request.status = "held_for_customer_match"
                            quote_request.parsed_data = {
                                **(quote_request.parsed_data or {}),
                                "configurator_mapping": mapping,
                                "field_sources": quote_request.field_sources,
                            }
                            db.commit()
                            return
                        elif not match.confident:
                            logger.info("  -> %s", match.reason)
                            quote_request.status = "held_for_customer_match"
                            db.commit()
                            return
                        else:
                            customer_id = profile_customer_id
                            live_doors = profile_apply["doors"]
                            live_delivery = profile_apply["delivery_type"]
                            profile_applied = True
                            quote_request.matched_bc_customer_id = customer_id
                            quote_request.parsed_data = {
                                **(quote_request.parsed_data or {}),
                                "configurator_mapping": {**mapping, "doors": live_doors},
                                "field_sources": quote_request.field_sources,
                            }
                            if profile_apply.get("hold_for_review"):
                                logger.info(
                                    "  -> Held: explicit email differs from the customer standard"
                                )
                                quote_request.status = "held_for_standard_deviation"
                                db.commit()
                                return
                            delivery_explicit = True
                            logger.info("  -> %s", match.reason)
                    except Exception:
                        logger.exception(
                            "Customer profile quoting failed (mode=%s); live quote unchanged",
                            mode,
                        )
                        if mode != "shadow":
                            raise
                        customer_id = self._legacy_bc_customer_id(db, quote_request)
                        live_doors = [dict(door) for door in mapped_doors]
                        live_delivery = "delivery"
                        delivery_explicit = False
                        profile_applied = False

                from app.services.customer_profile_service import get_profile
                from app.services.quote_round3 import apply_round3
                profile_fields = None
                if customer_id:
                    nested = None
                    try:
                        nested = db.begin_nested()
                        profile_row = get_profile(db, customer_id)
                        nested.commit()
                        if profile_row is not None:
                            profile_fields = profile_row.fields or {}
                    except Exception:
                        logger.exception("Could not read the customer profile for round 3. Continuing.")
                        if nested is not None:
                            try:
                                nested.rollback()
                            except Exception:
                                pass
                        profile_fields = None
                round3 = apply_round3(
                    db,
                    live_doors,
                    email_text=quote_email_text(
                        subject, body, getattr(email_log, "attachments", None),
                    ),
                    parsed_doors=doors,
                    profile_fields=profile_fields,
                )
                if round3.shadow_notes:
                    quote_request.parsed_data = {
                        **(quote_request.parsed_data or {}),
                        "round3_shadow": round3.shadow_notes,
                    }
                if round3.applied:
                    live_doors = round3.doors
                    if round3.delivery_type:
                        live_delivery = round3.delivery_type
                        delivery_explicit = True
                    if round3.deviations:
                        quote_request.deviations = list(quote_request.deviations or []) + round3.deviations
                    quote_request.parsed_data = {
                        **(quote_request.parsed_data or {}),
                        "configurator_mapping": {
                            **((quote_request.parsed_data or {}).get("configurator_mapping") or mapping),
                            "doors": live_doors,
                        },
                    }

                cfg_request = QuoteGenerationRequest(
                    doors=[DoorConfigRequest(**{k: v for k, v in d.items() if k != "_touched"}) for d in live_doors],
                    customerId=customer_id,
                    tagName=(project.get("tag") or project.get("name")
                             or quote_request.customer_name or "Email Quote"),
                    poNumber=f"EMAIL-QR-{quote_request.id}",
                    deliveryType=live_delivery,
                    deliveryExplicit=delivery_explicit,
                    profileApplied=profile_applied,
                )

                logger.info(f"  -> Generating BC quote via configurator for {len(mapped_doors)} door(s)")
                result = build_bc_quote_from_doors(cfg_request, db, source="email")
                data = result.get("data", {}) if isinstance(result, dict) else {}
                bc_quote_number = data.get("bc_quote_number")

                # Mirror the configurator's BC line pricing into local QuoteItems
                # so the existing review UI shows real BC prices, not placeholders.
                self._persist_quote_items_from_pricing(
                    db, quote_request.id, data.get("line_pricing") or []
                )

                if mode != "off":
                    part_deviations = list(data.get("deviations") or [])
                    quote_request.deviations = merge_part_deviations(
                        quote_request.deviations, part_deviations
                    )
                    if mode == "shadow":
                        quote_request.deviations = [
                            {**item, "shadow": True} if isinstance(item, dict) else item
                            for item in (quote_request.deviations or [])
                        ]

                if bc_quote_number:
                    quote_request.bc_quote_id = bc_quote_number
                    quote_request.status = "bc_created"
                    logger.info(
                        f"  -> BC Quote created via configurator: {bc_quote_number} "
                        f"(total ${(data.get('pricing') or {}).get('total', 0):.2f})"
                    )
                    try:
                        memory_service.learn_customer_preferences(
                            customer_email=quote_request.contact_email,
                            customer_name=quote_request.customer_name,
                            quote_request=quote_request
                        )
                    except Exception as e:
                        logger.warning(f"Failed to learn customer preferences: {e}")
                else:
                    quote_request.status = "quote_generated"
                    logger.warning("  -> Configurator returned no BC quote number")

                self._settle_followups(db, quote_request, email_log, mailbox, graph_message_id)
                db.commit()

            except HTTPException as he:
                # Configurator rejected the config (unstocked combo, panel not
                # in BC, etc.) — it already cleaned up any partial BC quote.
                logger.warning(f"  -> Configurator validation failed ({he.detail}); manual review")
                try:
                    db.rollback()
                except Exception:
                    pass
                quote_request.status = "needs_manual_review"
                self._settle_followups(db, quote_request, email_log, mailbox, graph_message_id)
                db.commit()
            except Exception as e:
                logger.error(f"  -> Auto-generation failed: {e}", exc_info=True)
                # Don't fail the whole parse - just log and continue
                try:
                    db.rollback()
                except Exception:
                    pass
                quote_request.status = "pending"  # Fall back to manual review
                db.commit()
        else:
            self._settle_followups(db, quote_request, email_log, mailbox, graph_message_id)
            db.commit()

    def _legacy_bc_customer_id(self, db, quote_request: QuoteRequest) -> Optional[str]:
        """Exact email, then exact company name. None falls back to retail."""
        from app.services.customer_profile_service import legacy_customer_id
        found = legacy_customer_id(db, quote_request.contact_email, quote_request.customer_name)
        if found:
            logger.info("  -> Matched BC customer %s", found)
        else:
            logger.info("  -> No BC customer match; using CASH/retail pricing")
        return found

    def _match_bc_customer(self, db, quote_request: QuoteRequest):
        """Domain, known contact, or fuzzy company name, plus the exact matches."""
        from app.services.customer_profile_service import match_bc_customer
        return match_bc_customer(
            db,
            email=quote_request.contact_email,
            company_name=quote_request.customer_name,
        )

    def _resolve_bc_customer_id(self, db, quote_request: QuoteRequest) -> Optional[str]:
        """Customer id for pricing.

        With the switch off or in shadow this is the exact email / company
        name lookup, and None still means retail. With the switch on, None
        means there was no confident match and the caller holds the request.
        """
        from app.services.customer_profile_service import quoting_mode
        if quoting_mode(db) != "on":
            return self._legacy_bc_customer_id(db, quote_request)
        match = self._match_bc_customer(db, quote_request)
        if match.confident:
            logger.info("  -> %s", match.reason)
            return match.bc_customer_id
        logger.info("  -> %s", match.reason)
        return None

    def _persist_quote_items_from_pricing(self, db, quote_request_id: int,
                                          line_pricing: List[Dict[str, Any]]):
        """Mirror the configurator's BC line pricing into local QuoteItem rows.

        Keeps the existing review/approval UI working while ensuring the prices
        it shows are the authoritative BC SalesPriceLists prices, not the
        legacy placeholder margins.
        """
        db.query(QuoteItem).filter(
            QuoteItem.quote_request_id == quote_request_id
        ).delete()
        for line in line_pricing:
            try:
                qty = int(round(float(line.get("quantity", 1) or 1)))
            except (TypeError, ValueError):
                qty = 1
            db.add(QuoteItem(
                quote_request_id=quote_request_id,
                item_type="door_part",
                product_code=line.get("part_number"),
                description=(line.get("description") or "")[:1000],
                quantity=qty,
                unit_price=line.get("unit_price", 0) or 0,
                total_price=line.get("line_total", 0) or 0,
                item_metadata={"source": "configurator"},
            ))

    def _parse_quote_modification(self, db, email_log: EmailLog, subject: str, body: str,
                                   from_name: str, from_address: str,
                                   referenced_quote_number: Optional[str],
                                   modification_type: Optional[str]):
        """Parse quote modification and link to original quote"""

        # Step 1: Try to find the original quote request
        original_quote = None

        if referenced_quote_number:
            # Try by BC quote ID
            original_quote = db.query(QuoteRequest).filter(
                QuoteRequest.bc_quote_id == referenced_quote_number
            ).first()

            if not original_quote:
                # Try by our internal AI-QR-xxx format
                if referenced_quote_number.startswith("AI-QR-"):
                    try:
                        qr_id = int(referenced_quote_number.replace("AI-QR-", ""))
                        original_quote = db.query(QuoteRequest).filter(
                            QuoteRequest.id == qr_id
                        ).first()
                    except ValueError:
                        pass

        if not original_quote:
            # Try by customer email - get the most recent quote
            original_quote = db.query(QuoteRequest).filter(
                QuoteRequest.contact_email == from_address
            ).order_by(QuoteRequest.created_at.desc()).first()

            if original_quote:
                logger.info(f"  -> Found original quote by customer email: QR-{original_quote.id}")

        # Step 2: Parse the email for modifications
        sender_info = {"name": from_name, "email": from_address}
        memory_service = get_memory_service(db)
        examples = memory_service.retrieve_similar_examples(subject, body, max_examples=3)
        example_context = memory_service.format_examples_for_prompt(examples)

        parse_result = self.ai_client.parse_email_for_quote(
            subject, body, sender_info, example_context=example_context
        )

        if not parse_result.get("success"):
            logger.error(f"Failed to parse quote modification: {parse_result.get('error')}")
            email_log.status = "error"
            return

        parsed_data = parse_result.get("data", {})
        confidence = parse_result.get("confidence", 0.0)
        customer = parsed_data.get("customer", {})
        doors = parsed_data.get("doors", [])

        # Step 3: Create the revision QuoteRequest
        revision_number = 1
        if original_quote:
            # Get the next revision number
            existing_revisions = db.query(QuoteRequest).filter(
                QuoteRequest.parent_quote_id == original_quote.id
            ).count()
            revision_number = existing_revisions + 2  # 1 = original, 2+ = revisions

        quote_request = QuoteRequest(
            email_id=email_log.id,
            customer_name=customer.get("company_name") or customer.get("contact_name") or (original_quote.customer_name if original_quote else None),
            contact_email=customer.get("email") or from_address,
            contact_phone=customer.get("phone") or (original_quote.contact_phone if original_quote else None),
            door_specs={"doors": doors} if doors else (original_quote.door_specs if original_quote else None),
            parsed_data=parsed_data,
            confidence_scores={
                "overall": confidence,
                "customer": customer.get("confidence", 0.0),
            },
            status="modification_pending",  # Special status for modifications
            # Modification tracking fields
            is_modification=True,
            parent_quote_id=original_quote.id if original_quote else None,
            revision_number=revision_number,
            modification_type=modification_type,
            modification_notes=f"Modification detected from email. Original quote: {original_quote.bc_quote_id if original_quote else 'NOT FOUND - needs review'}"
        )
        db.add(quote_request)
        db.flush()

        # Step 4: Record AI decision for audit
        ai_decision = AIDecision(
            quote_request_id=quote_request.id,
            decision_type="email_parse_modification",
            input_data={
                "subject": subject,
                "body_preview": body[:500],
                "original_quote_id": original_quote.id if original_quote else None
            },
            output_data=parsed_data,
            confidence_score=confidence,
            model_used=parse_result.get("model", settings.ANTHROPIC_MODEL),
            prompt_tokens=parse_result.get("tokens", {}).get("input", 0),
            completion_tokens=parse_result.get("tokens", {}).get("output", 0),
            created_at=datetime.utcnow()
        )
        db.add(ai_decision)

        email_log.status = "parsed"
        email_log.parsed_at = datetime.utcnow()

        if original_quote:
            logger.info(f"  -> Quote MODIFICATION parsed. Linked to original QR-{original_quote.id} "
                       f"(BC: {original_quote.bc_quote_id}), Revision #{revision_number}")
        else:
            logger.info(f"  -> Quote MODIFICATION parsed. Original NOT FOUND - flagged for review. "
                       f"Modification type: {modification_type}")
            # If we couldn't find the original, put it in review queue
            quote_request.status = "needs_original_link"

        db.commit()

    def get_pending_quote_requests(self, min_confidence: float = 0.0) -> List[QuoteRequest]:
        """Get quote requests pending review

        Args:
            min_confidence: Minimum confidence score (0.0 to 1.0)

        Returns:
            List of QuoteRequest objects
        """
        db = SessionLocal()
        try:
            query = db.query(QuoteRequest).filter(
                QuoteRequest.status.in_(["pending", "low_confidence"])
            )

            if min_confidence > 0:
                # Filter by overall confidence in confidence_scores JSON
                # This is a simplified filter - in production you'd use JSON operators
                results = [qr for qr in query.all()
                          if qr.confidence_scores.get("overall", 0) >= min_confidence]
            else:
                results = query.all()

            return results

        finally:
            db.close()

    def get_stats(self) -> Dict[str, Any]:
        """Get monitoring statistics"""
        db = SessionLocal()
        try:
            total_emails = db.query(EmailLog).count()
            parsed_emails = db.query(EmailLog).filter(EmailLog.status == "parsed").count()
            pending_quotes = db.query(QuoteRequest).filter(
                QuoteRequest.status.in_(["pending", "low_confidence"])
            ).count()

            # Get recent activity (last 24 hours)
            yesterday = datetime.utcnow() - timedelta(hours=24)
            recent_emails = db.query(EmailLog).filter(
                EmailLog.received_at >= yesterday
            ).count()

            return {
                "total_emails_logged": total_emails,
                "total_emails_parsed": parsed_emails,
                "pending_quote_requests": pending_quotes,
                "emails_last_24h": recent_emails
            }

        finally:
            db.close()


# Global email monitor instance
email_monitor = EmailMonitorService()
