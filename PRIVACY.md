# Privacy statement

*Nederlands: [PRIVACY.nl.md](PRIVACY.nl.md).*

This statement describes what the CNX Toolkit web app does with data. It applies to the hosted version (`cnx web
--server`, for example on Azure) and to the local app on your own PC. Whoever runs an instance of the toolkit is
responsible for that instance; the toolkit itself is built so that the server stores nothing.

## In short

- **No account, no database, nothing stored on the server.** The server keeps data only in memory, for as long as it
  needs it, and writes nothing to disk.
- **No analytics, no trackers, no advertising.** The page loads nothing from other sites.
- **Your Central credentials** (API URL, client ID, secret) stay only in the memory of your session and disappear
  when you sign out, after 30 minutes without activity, or when the server restarts.

## What is processed where

| Data | Where | How long |
|---|---|---|
| Central API URL, client ID and secret, and the access token | Server memory, in your session | Until you sign out, 30 minutes without activity, or a restart |
| Data read from your Central (devices, serial numbers, IP addresses, hostnames, aliases, profiles) | Server memory, to build the screens and files you ask for | For the session; results of long tasks are kept at most for the session |
| Files you upload (AOS-8 inventory, CSV) | Server memory, only while processing the request | A few seconds |
| AP migration: inventory, ticked steps, chosen clusters | Your browser (local storage), per customer name | Until you click Forget in the AP migration tab, or clear the site data |
| Preferences: last API URL (not the secret), device group, site, prefix, open tab, table filters | Your browser (local storage) | Until you delete them |
| Your IP address | Server memory, only to limit new sessions per visitor (1 minute) and wrong pilot codes (15 minutes) | At most 15 minutes; never logged |
| Logs | The server's console output: date and time, method, path without parameters, status code and duration | As long as the hosting platform keeps console output |

The logs contain no IP addresses, no parameters (such as device groups, serial numbers or tokens), and no content.

## Cookies

| Cookie | Purpose | Lifetime |
|---|---|---|
| `cnx_sessie` | Links your browser to your session on the server (HttpOnly, Secure, SameSite=Strict) | Until you close the browser; the session itself ends after 30 minutes without activity |
| `cnx_taal` | Your language choice (NL or EN) | 1 year |

Both are strictly necessary for the app to work; there are no other cookies.

## Who receives data

- **HPE (your own new Central and HPE GreenLake):** the toolkit sends your client ID and secret to HPE's sign-in
  service and then calls the API of the Central you entered, on your behalf. That data stays within your own HPE
  environment.
- **The hosting provider** (for the public instance at cnx.caersultancy.com: Microsoft Azure Container Apps, region North Europe) runs the
  server and its network. Azure keeps technical platform metrics such as request counts and CPU usage. Log Analytics
  is not enabled.
- **Nobody else.** The server sends nothing to other parties.

## Your choices

- Sign out (top right) to remove your credentials from the server straight away.
- Click **Forget** in the AP migration tab to remove one customer's inventory and progress, or clear the site data in
  your browser to remove all stored AP migration data and preferences. Export a migration file
  first if you still need it.
- Use a separate Central API client for the toolkit, with only the rights it needs, and revoke it when you are done.
  The server never stores the secret, but whoever runs an instance could in principle read the memory of their own
  server. Only use an instance you trust, or run the toolkit yourself.

## Questions

Ask a question or report a problem on [GitHub](https://github.com/levicaers1-pixel/cnx-toolkit-web/issues) (without
customer data). Report a security problem privately: see [SECURITY.md](SECURITY.md).

*Last updated: 25 November 2026. This statement describes how the software works; it is not legal advice.*
