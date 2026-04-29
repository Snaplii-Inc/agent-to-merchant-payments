# Snaplii A2M Payment — MCP Plugin

Agent-to-Merchant (A2M) payments — where AI agents complete transactions without checkout. Snaplii uses pre-funded gift cards as a payment rail, enabling instant, merchant-ready execution across 500+ brands.

## Prerequisites

1. **Download the Snaplii App** ([iOS](https://apps.apple.com/app/snaplii/id1596924498) / [Android](https://play.google.com/store/apps/details?id=com.snaplii.app))
2. **Create an API Key** in the app: More → Payment Methods → AI Payment Management → + New API Key
3. **Install the MCP server**: `pip install snaplii-cli "mcp[cli]"`

## Tools

| Tool | Description |
|------|-------------|
| `snaplii_init` | Authenticate with API key (not stored) |
| `snaplii_config_show` | Show auth status |
| `snaplii_browse_tags` | Browse gift card categories (CA/US) |
| `snaplii_browse_brand` | Brand details and denominations |
| `snaplii_giftcard_list` | List owned gift cards |
| `snaplii_giftcard_detail` | Card redemption code (sensitive) |
| `snaplii_purchase` | Buy a gift card |
| `snaplii_apikey_list` | List API keys |
| `snaplii_apikey_create` | Create API key |
| `snaplii_apikey_delete` | Delete API key |
| `snaplii_cashback_calc` | Calculate cashback savings |
| `snaplii_dashboard` | Owned card inventory summary |
