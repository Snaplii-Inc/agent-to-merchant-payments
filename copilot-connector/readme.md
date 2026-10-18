# Snaplii

Snaplii is a prepaid payment account for AI agents: people load Snaplii Cash in the Snaplii app and let agents buy discounted gift cards from 500+ brands with vouchers and up to 10% cashback. This connector lets Copilot Studio agents and flows browse the gift card catalog, read the user's Snaplii Cash balance and get an exact price quote before buying. It does not buy cards or move money.

## Publisher: Snaplii Inc.

## Prerequisites

- A Snaplii account in Canada or the United States, created in the Snaplii app for [iOS](https://apps.apple.com/app/snaplii/id1596924498) or [Android](https://play.google.com/store/apps/details?id=com.snaplii.app).
- A Snaplii API key created in the Snaplii app.

## Supported Operations

### List gift card categories and brands
Returns the gift card categories shown on the Snaplii app home page, each with its brands and their cashback rates.

### Get gift card brand details and denominations
Returns a brand's cards and their denominations. A FIXED card has one amount; a VARIABLE card accepts any amount between its minimum and maximum.

### Get Snaplii Cash balance
Returns the user's spendable Snaplii Cash balance.

### Quote a gift card purchase
Returns the price breakdown for one card and amount: the order amount, any voucher discount, the Snaplii Cash applied and the amount still to pay. A quote charges nothing.

## Obtaining Credentials

The connector authenticates with an API key. In the Snaplii app, go to More, Payment Methods, AI Payment Management, then New API Key. Choose a name, the scope and a spending limit, and copy the key; it is shown only once. Enter it when you create the connection. The connector exchanges the key for a short-lived access token on every call, and the key can be revoked in the app at any time.

## Getting Started

1. Create a connection with your Snaplii API key.
2. Call **List gift card categories and brands** and pick a brand.
3. Call **Get gift card brand details and denominations** with that brand's ID and pick a card and amount.
4. Call **Quote a gift card purchase** with the card ID, which is the brand ID, one hyphen and the card template ID, both copied from the brand details, and the amount.

## Known Issues and Limitations

- Available for Snaplii accounts in Canada and the United States only. The account's country decides the catalog and the currency.
- The connector reads the catalog, the balance and quotes. It does not buy gift cards, pay bills or send money.
- The catalog lists the brands shown on the Snaplii app home page.
- Spending comes only from prepaid Snaplii Cash. A quote with an amount still to pay greater than zero means the balance does not cover the order.
- The card ID in a quote must be copied exactly from the brand details; a malformed or guessed ID is rejected.
- Some gateway errors arrive with HTTP status 200 and an error code in `rspMsgCd`; check it on every reply.

## Deployment Instructions

Download `apiDefinition.swagger.json`, `apiProperties.json` and `script.csx` from this folder, then create the custom connector with the [Power Platform Connectors CLI](https://learn.microsoft.com/en-us/connectors/custom-connectors/paconn-cli):

```
paconn create --api-def apiDefinition.swagger.json --api-prop apiProperties.json --script script.csx
```
