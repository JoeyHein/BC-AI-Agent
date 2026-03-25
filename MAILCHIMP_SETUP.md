# Mailchimp Setup for OPENDC Weekly Email Agent

## 1. Get Your Mailchimp API Key

1. Log in to [Mailchimp](https://login.mailchimp.com/)
2. Click your profile icon (bottom-left) > **Profile**
3. Go to **Extras** > **API keys**
4. Click **Create A Key**
5. Copy the full key (looks like `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx-usXX`)

Add to your `.env`:
```
MAILCHIMP_API_KEY=your-full-api-key-here
```

## 2. Find Your Server Prefix

Your server prefix is in your Mailchimp URL after login.

Look at the URL bar: `https://us14.admin.mailchimp.com/...`

The `us14` part is your server prefix.

```
MAILCHIMP_SERVER_PREFIX=us14
```

## 3. Find Your Audience ID

1. In Mailchimp, go to **Audience** > **All contacts**
2. Click **Settings** (dropdown) > **Audience name and defaults**
3. Scroll down to find the **Audience ID** (looks like `a1b2c3d4e5`)

```
MAILCHIMP_AUDIENCE_ID=your-audience-id
```

## 4. Set the From Email Address

The "from" email must be verified in Mailchimp:

1. Go to **Settings** > **Domains**
2. Verify your sending domain (opendc.ca) or specific email address
3. Update `.env` if needed:

```
MAILCHIMP_FROM_NAME=Joey @ OPENDC
MAILCHIMP_FROM_EMAIL=joey@opendc.com
```

## 5. Verify the Integration

After setting all four env vars, restart the backend and:

1. Log in to the portal as admin
2. Go to the **Email** tab in the nav
3. You should see the subscriber count in the top-right corner
4. Fill in a test brief and hit **Generate Email**
5. Review the preview, then **Send via Mailchimp**

If you see a "Mailchimp not configured" warning, double-check your `.env` values.

## Full .env Example

```
MAILCHIMP_API_KEY=abc123def456-us14
MAILCHIMP_SERVER_PREFIX=us14
MAILCHIMP_AUDIENCE_ID=a1b2c3d4e5
MAILCHIMP_FROM_NAME=Joey @ OPENDC
MAILCHIMP_FROM_EMAIL=joey@opendc.com
```
