"""
Notification Service
Sends email notifications via Microsoft Graph API
"""

import logging
import requests
from typing import Optional, List
from app.config import settings

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending email notifications via Microsoft Graph API"""

    def __init__(self):
        self.tenant_id = settings.GRAPH_TENANT_ID
        self.client_id = settings.GRAPH_CLIENT_ID
        self.client_secret = settings.GRAPH_CLIENT_SECRET
        self.sender_email = settings.NOTIFICATION_SENDER_EMAIL
        self.admin_emails = [e.strip() for e in settings.ADMIN_NOTIFICATION_EMAILS.split(',')]
        self.customer_portal_url = settings.CUSTOMER_PORTAL_URL
        self.admin_portal_url = settings.ADMIN_PORTAL_URL
        self.enabled = getattr(settings, 'ENABLE_CUSTOMER_NOTIFICATIONS', True)
        self._access_token = None

    def _get_access_token(self) -> Optional[str]:
        """Get access token using client credentials flow"""
        if not all([self.tenant_id, self.client_id, self.client_secret]):
            logger.warning("Graph API credentials not configured")
            return None

        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"

        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'scope': 'https://graph.microsoft.com/.default',
            'grant_type': 'client_credentials'
        }

        try:
            response = requests.post(token_url, data=data)
            response.raise_for_status()
            self._access_token = response.json().get('access_token')
            return self._access_token
        except requests.RequestException as e:
            logger.error(f"Error getting Graph API access token: {e}")
            return None

    def send_email(
        self,
        to_emails: List[str],
        subject: str,
        body: str,
        is_html: bool = True
    ) -> bool:
        """
        Send email via Microsoft Graph API

        Args:
            to_emails: List of recipient email addresses
            subject: Email subject
            body: Email body (HTML or plain text)
            is_html: Whether body is HTML

        Returns:
            True if email sent successfully
        """
        access_token = self._get_access_token()
        if not access_token:
            logger.error("Cannot send email: No access token")
            return False

        # Use the sender email or first admin email
        sender = self.sender_email

        url = f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail"

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

        message = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "HTML" if is_html else "Text",
                    "content": body
                },
                "toRecipients": [
                    {"emailAddress": {"address": email}} for email in to_emails
                ]
            },
            "saveToSentItems": "true"
        }

        try:
            response = requests.post(url, headers=headers, json=message)
            response.raise_for_status()
            logger.info(f"Email sent successfully to {to_emails}")
            return True
        except requests.RequestException as e:
            logger.error(f"Error sending email: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            return False

    def notify_admins_new_customer(
        self,
        customer_email: str,
        customer_name: str,
        company_name: Optional[str] = None,
        bc_matched: bool = False
    ) -> bool:
        """
        Notify admins about a new customer registration

        Args:
            customer_email: New customer's email
            customer_name: New customer's name
            company_name: Customer's company name (if provided)
            bc_matched: Whether customer was auto-matched to BC customer

        Returns:
            True if notification sent successfully
        """
        subject = f"New Customer Registration: {customer_name}"

        bc_status = "Matched to existing BC customer" if bc_matched else "Not linked to BC customer yet"

        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6;">
            <h2 style="color: #2563eb;">New Customer Portal Registration</h2>

            <table style="border-collapse: collapse; width: 100%; max-width: 500px;">
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #e5e7eb; font-weight: bold;">Name:</td>
                    <td style="padding: 8px; border-bottom: 1px solid #e5e7eb;">{customer_name}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #e5e7eb; font-weight: bold;">Email:</td>
                    <td style="padding: 8px; border-bottom: 1px solid #e5e7eb;">{customer_email}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #e5e7eb; font-weight: bold;">Company:</td>
                    <td style="padding: 8px; border-bottom: 1px solid #e5e7eb;">{company_name or 'Not provided'}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #e5e7eb; font-weight: bold;">BC Status:</td>
                    <td style="padding: 8px; border-bottom: 1px solid #e5e7eb;">
                        <span style="color: {'#16a34a' if bc_matched else '#ca8a04'};">{bc_status}</span>
                    </td>
                </tr>
            </table>

            <p style="margin-top: 20px; color: #6b7280;">
                {'This customer was automatically linked to their BC account.' if bc_matched else 'You may need to manually link this customer to their BC account in the admin panel.'}
            </p>

            <p style="margin-top: 20px;">
                <a href="{self.admin_portal_url}/customers"
                   style="background-color: #2563eb; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">
                    View in Admin Panel
                </a>
            </p>
        </body>
        </html>
        """

        if not self.enabled:
            logger.info(f"Notifications disabled - would have sent admin notification for {customer_email}")
            return True

        return self.send_email(self.admin_emails, subject, body)

    def send_customer_welcome_email(
        self,
        customer_email: str,
        customer_name: str,
        verification_link: Optional[str] = None
    ) -> bool:
        """
        Send welcome email to new customer

        Args:
            customer_email: Customer's email
            customer_name: Customer's name
            verification_link: Email verification link (if email verification enabled)

        Returns:
            True if email sent successfully
        """
        subject = "Welcome to OPENDC Customer Portal"

        verification_section = ""
        if verification_link:
            verification_section = f"""
            <div style="background-color: #fef3c7; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <p style="margin: 0; color: #92400e;">
                    <strong>Please verify your email address</strong><br>
                    Click the button below to verify your email and activate your account.
                </p>
                <p style="margin-top: 15px;">
                    <a href="{verification_link}"
                       style="background-color: #2563eb; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">
                        Verify Email
                    </a>
                </p>
            </div>
            """

        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; max-width: 600px; margin: 0 auto;">
            <div style="background-color: #2563eb; color: white; padding: 20px; text-align: center;">
                <h1 style="margin: 0;">OPENDC</h1>
                <p style="margin: 5px 0 0 0;">Customer Portal</p>
            </div>

            <div style="padding: 30px;">
                <h2 style="color: #1f2937;">Welcome, {customer_name}!</h2>

                <p>Thank you for registering with the OPENDC Customer Portal. Your account has been created successfully.</p>

                {verification_section}

                <h3 style="color: #1f2937; margin-top: 30px;">What you can do:</h3>
                <ul>
                    <li>Create and save door configuration quotes</li>
                    <li>Submit quotes for processing</li>
                    <li>Track your orders and shipments</li>
                    <li>View your order history and invoices</li>
                </ul>

                <p style="margin-top: 30px;">
                    <a href="{self.customer_portal_url}"
                       style="background-color: #2563eb; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; display: inline-block;">
                        Go to Customer Portal
                    </a>
                </p>

                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">

                <p style="color: #6b7280; font-size: 14px;">
                    If you have any questions, please contact us at support@opendc.com
                </p>
            </div>
        </body>
        </html>
        """

        if not self.enabled:
            logger.info(f"Notifications disabled - would have sent welcome email to {customer_email}")
            return True

        return self.send_email([customer_email], subject, body)


    def send_password_reset_email(
        self,
        customer_email: str,
        customer_name: str,
        reset_link: str
    ) -> bool:
        """
        Send password reset email to customer

        Args:
            customer_email: Customer's email
            customer_name: Customer's name
            reset_link: Password reset link with token

        Returns:
            True if email sent successfully
        """
        subject = "Reset Your OPENDC Password"

        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; max-width: 600px; margin: 0 auto;">
            <div style="background-color: #2563eb; color: white; padding: 20px; text-align: center;">
                <h1 style="margin: 0;">OPENDC</h1>
                <p style="margin: 5px 0 0 0;">Customer Portal</p>
            </div>

            <div style="padding: 30px;">
                <h2 style="color: #1f2937;">Password Reset Request</h2>

                <p>Hi {customer_name},</p>

                <p>We received a request to reset your password for your OPENDC Customer Portal account.</p>

                <div style="background-color: #f3f4f6; padding: 20px; border-radius: 5px; margin: 20px 0; text-align: center;">
                    <a href="{reset_link}"
                       style="background-color: #2563eb; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold;">
                        Reset Password
                    </a>
                </div>

                <p style="color: #6b7280; font-size: 14px;">
                    This link will expire in 1 hour for security reasons.
                </p>

                <p style="color: #6b7280; font-size: 14px;">
                    If you didn't request a password reset, you can safely ignore this email.
                    Your password will not be changed.
                </p>

                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">

                <p style="color: #6b7280; font-size: 14px;">
                    If you have any questions, please contact us at support@opendc.com
                </p>
            </div>
        </body>
        </html>
        """

        if not self.enabled:
            logger.info(f"Notifications disabled - would have sent password reset email to {customer_email}")
            return True

        return self.send_email([customer_email], subject, body)

    def send_email_verification(
        self,
        customer_email: str,
        customer_name: str,
        verification_link: str
    ) -> bool:
        """
        Send email verification email to customer

        Args:
            customer_email: Customer's email
            customer_name: Customer's name
            verification_link: Email verification link with token

        Returns:
            True if email sent successfully
        """
        subject = "Verify Your OPENDC Email Address"

        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; max-width: 600px; margin: 0 auto;">
            <div style="background-color: #2563eb; color: white; padding: 20px; text-align: center;">
                <h1 style="margin: 0;">OPENDC</h1>
                <p style="margin: 5px 0 0 0;">Customer Portal</p>
            </div>

            <div style="padding: 30px;">
                <h2 style="color: #1f2937;">Verify Your Email Address</h2>

                <p>Hi {customer_name},</p>

                <p>Thank you for registering with the OPENDC Customer Portal. Please verify your email address to complete your registration.</p>

                <div style="background-color: #f3f4f6; padding: 20px; border-radius: 5px; margin: 20px 0; text-align: center;">
                    <a href="{verification_link}"
                       style="background-color: #16a34a; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold;">
                        Verify Email Address
                    </a>
                </div>

                <p style="color: #6b7280; font-size: 14px;">
                    This link will expire in 24 hours.
                </p>

                <p style="color: #6b7280; font-size: 14px;">
                    If you didn't create an account with us, you can safely ignore this email.
                </p>

                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">

                <p style="color: #6b7280; font-size: 14px;">
                    If you have any questions, please contact us at support@opendc.com
                </p>
            </div>
        </body>
        </html>
        """

        if not self.enabled:
            logger.info(f"Notifications disabled - would have sent verification email to {customer_email}")
            return True

        return self.send_email([customer_email], subject, body)


# Global instance
notification_service = NotificationService()
