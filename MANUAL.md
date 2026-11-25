# CNX Toolkit

Tools to bring network devices into HPE Aruba Networking Central (new Central) and keep them tidy there: onboard
AOS-CX switches and Mobility Gateways, clean up local overrides, and plan the move from AOS-8 to AOS-10 for access
points. Free open-source software, not made or supported by HPE.

*Nederlands: zie [LEESMIJ.md](LEESMIJ.md), of kies NL bovenaan in de app.*

## Three ways to use the toolkit

| Way | For whom | How |
|---|---|---|
| Hosted web app | Anyone who does not want to install anything | Open the address you received. See [Hosted version](#hosted-version) |
| `cnx.exe` on Windows | Anyone working locally, also on the command line | Unzip and double-click `cnx.exe`. See [Installing](#installing) |
| Container | Anyone hosting it themselves | `docker run` with the image from GHCR. See [docs/AZURE.md](docs/AZURE.md) and the README |

The web app is the same everywhere. At the top right you choose the language (**NL** or **EN**); your browser
remembers the choice.

## Web app

| Tab | What |
|---|---|
| Onboarding | Choose a device group in new Central, select switches and gateways, review IP and hostname, and download the import file (aliases). See [Onboarding](#onboarding) |
| Check overrides | What is set locally on a switch compared with what it inherits, for profiles and aliases, and removing overrides. See [Check overrides](#check-overrides) |
| AP migration | Read in an AOS-8 inventory of the mobility conductor and see what is ready for AOS-10, with a report and a migration plan per cluster. See [AP migration](#ap-migration) |
| Settings | Only in the local app: fill in `klantconfig.json` for `cnx alias` on the command line |
| Manual | This manual |

**Signing in.** Click Sign in at the top right and enter the API URL of your new Central (e.g.
`https://de1.api.central.arubanetworks.com`), a client ID and a secret. They stay only in the toolkit's memory, for your
session, and are never stored. A Central token expires after a while; the toolkit then signs in again by itself. AP
migration does not need a sign-in.

### Onboarding

For switches and Mobility Gateways. Three screens, no customer config needed:

1. **Choose devices.** Choose the device group and click Fetch devices. Per switch the toolkit reads from Central:
   hostname, site, site collection, device function, the System-info profile and the management IP. If the switch
   already has an alias `sys_vlan_ipv4_<vlan>` (switches from Classic), the IP, prefix and VLAN come from it;
   otherwise the IP comes from monitoring with the prefix you enter, and the management VLAN set on Global. Select the
   devices you want.
   - **Gateways** in the same device group are included, with Device Function *Mobility Gateway* in the import file.
     Their management IP comes only from the alias `sys_vlan_ipv4_<vlan>` on the gateway: the IP in monitoring is
     usually the uplink's (e.g. DHCP on VLAN 4094) and is not used. If there is no alias yet, fill in the management
     IP (e.g. the controller's IP in AOS-8). Other aliases on the gateway are left alone.
2. **Review.** A table with hostname, device function, IP, VLAN and System-info profile per device, all editable,
   also for all devices at once. Errors (invalid or duplicate IP, invalid VLAN) turn red straight away; as long as
   there are errors you cannot continue. An empty or invalid hostname is not an error: then only the IP is included.
   An empty System-info profile stands out; choose the profile the device has in Central.
3. **File.** A preview of the import file as Central receives it, with a Download button. Upload it through
   Configuration > Library > Named Objects > Aliases > Bulk upload, then check a device. The local app also keeps a copy
   in `cnx-web/onboarding`.

### Check overrides

- **On the left** you filter the switches by device group and site, and scan the shown (or selected) switches. After
  the scan each switch shows how many objects are different, redundant or only on that switch.
- **On the right**, after a scan, you see a table per switch with a verdict (in order, clean up, to review); click a
  switch for the details: counters, a short summary, removal, and everything set locally.
- Two tabs: **Profiles** and **Aliases**. Everything can be exported to CSV.
- The requests to Central and any profiles that could not be read are collapsed under Technical details.

The toolkit reads everything set locally on the switch (VLANs, SVIs, system, DNS, NTP, logging, SNMP, port and
interface profiles, management, AAA, STP, LLDP, VSF, firmware policy and aliases) and compares it field by field with
what the switch inherits from the nearest higher scope that has the object: device group, then site, site collection,
Global.

| Word | Meaning | After removal |
|---|---|---|
| different | Locally different from what it inherits; you see both values per field | The switch takes over the value it inherits from above: its behaviour changes |
| redundant | Locally equal to what it inherits | The switch inherits the same value: nothing changes |
| only on this switch | Set nowhere above | The object disappears from the switch |
| per switch (normal) | Meant to differ per switch (hostname, management IP) | Never removed |

**Removing overrides** always takes two steps. Tick what may go and click Make a plan: the toolkit checks again in
Central that each object still has the same status (anything that changed in the meantime drops out) and shows the
effect per object. Only **Really remove** removes anything. If objects in the plan change the switch, you type DELETE
to confirm. Central refuses to remove an object that is still in use (e.g. a VLAN on a port); the result shows it as
"in use, not removed". After removal the toolkit checks that the object is gone. System info, management interface,
local management and firmware policy are never removed. With **Download log** you keep a record of what happened; the
local app also writes it to `cnx-web/overrides-wissen-log-<time>.json`.

### AP migration

For the move from AOS-8 (mobility conductor and controllers) to AOS-10 in new Central. It only reads files: nothing is
changed and you do not need to sign in.

1. On the mobility conductor, take the output of `show ap database long` and `show switches`, each as a text file (or
   together in one file). An Excel (.xlsx) or CSV file with the same columns works too.
2. Choose the files in the AP migration tab and click Read.
3. You get:
   - **Models**: per AP and controller model whether it supports AOS-10: *ready*, *end approaching* (can move, but
     support ends soon), *replace*, *goes away* (the conductor) or *to review* (unknown model).
   - **Clusters**: controllers that are each other's standby (from the APs' Standby IP). With two or more you migrate
     step by step without losing the tunneled SSIDs; with one controller you need a maintenance window or a temporary
     gateway. A cluster with APs that must be replaced is shown as blocked.
   - **AP groups**: the basis for the mapping to sites and device groups in Central.
   - **To clean up**: APs in the group default, without a name (MAC as name), down or with a duplicate name, and
     controllers that are down or have no APs.
   - **Download report (HTML)**: the same data as a report for the customer, printable as PDF.
4. **Migration plan**: tick the clusters you migrate in one wave and click Make step plan. You get a customer-wide part
   (once: GreenLake and subscriptions, AOS-10 version, structure and wireless configuration in Central, RADIUS
   clients, reachability, lab test) and per cluster the phases Prepare, First gateway (or Convert the gateway for a
   cluster with one controller), Convert APs (one step per AP group), Second gateway and Finish, with a fallback plan
   and the list of APs.
   - Tick off steps as you work. The inventory and the ticked steps are kept per customer in this browser, never on
     the server; type the customer name and the toolkit loads them again.
   - **Export** creates a migration file (`.json`) with the inventory, the ticked steps and the chosen clusters. With
     **Load migration file...** you continue on another PC or hand the plan over.
   - **Download step plan (HTML)** gives the plan with the ticked steps, for the engineer or the customer.
   - Steps marked *check* contain commands that can differ per AOS-8 version (converting controllers and APs): check
     them in HPE's migration guide before you run them.
   - The report and the plan come in the language you chose at the top right.

The support status per model is in `aos10-modellen.json` in the toolkit, with the date of the list. Check it for the
AOS-10 version you use on HPE's Supported Access Point Platforms and Supported Gateway Platforms pages.

## Hosted version

The web app can also run on a server, for several users (`cnx web --server`, or the container image).

- Each browser gets its own session and signs in to its own Central. The server stores nothing: no database, nothing
  on disk. After 30 minutes without activity, or on sign-out, the session and the secret are gone.
- During a pilot the administrator can set a **pilot code**: the app then asks for that code first.
- The Settings tab does not exist in the hosted version; import files and logs come as downloads.
- Hosting on Azure (free within the monthly grant): see [docs/AZURE.md](docs/AZURE.md) (Dutch). Technical details of
  the server mode: [docs/WEBAPP.md](docs/WEBAPP.md) (Dutch).

## Installing

For the local app on Windows (10 or 11, no Python needed):

1. Unzip into a folder, for example `C:\Tools\CNX Toolkit`.
2. Double-click `cnx.exe`: your browser opens the web app at `http://127.0.0.1:8766`. Close the black window to stop.
3. If Windows shows "Windows protected your PC" on the first start: click "More info" and then "Run anyway". That
   happens with every unsigned `.exe`.

Check: open PowerShell in that folder and type `.\cnx.exe --version`.

| Command | What it does |
|---|---|
| `cnx` | The web app (also when you double-click `cnx.exe`) |
| `cnx web` | The same, with options: `--poort` (port), `--map` (working folder), `--geen-browser` (no browser), `--zonder-opslag` (nothing on disk), `--server` (server mode, with `--host-naam` and `--adres`) |
| `cnx menu` | A menu in the window |
| `cnx alias ...` | Create and check upload files on the command line, for large lists. Also: convert a switch list from Classic, compare after the upload, analyse imported values |
| `cnx api ...` | Through the new Central API: create and assign aliases, clean up local values, push VLANs from Global to aggregation and core |
| `cnx sjablonen` | Put `klantconfig.json` and `toestellen-sjabloon.csv` in the current folder |
| `cnx hulp` | Open this manual |

The command-line tools (`cnx alias`, `cnx api`) and their messages are in Dutch.

## Requirements

- An API client in HPE GreenLake (Manage Workspace, Personal API clients) with access to new Central, for Onboarding,
  Check overrides and `cnx api`. Preferably use a separate client for this tool, with only the rights it needs, and
  revoke it after the migration.
- AP migration and `cnx alias` work without the API.

## Command line

### Customer config

`cnx alias` uses `klantconfig.json` from the folder where you start it. Create one with `.\cnx.exe sjablonen` and fill
it in, or use the Settings tab of the local app (with validation, and a proposal from a bulk download). Everything
with `VUL-IN` must go:

| Field | Meaning |
|---|---|
| `klant` | Customer name, for information only |
| `velden.hostname.instance` | Name of the shared System-info profile in new Central that holds the hostname of new switches. Optional: empty means only the IP is included (except for switches with their own system profile) |
| `velden.sys_vlan_ip.standaard_vlan` | Management VLAN. Central names the management IP alias `sys_vlan_ipv4_<vlan>` |
| `velden.mgmt_ip.instance` | Name of the management interface (OOBM), usually `mgmt` |
| `modified` | Leave it at `Yes`: Central only applies rows with `Yes` |

### API credentials

Per PowerShell window:

```powershell
$env:CNX_BASE_URL      = "https://de1.api.central.arubanetworks.com"
$env:CNX_CLIENT_ID     = "..."
$env:CNX_CLIENT_SECRET = "..."
```

Use the API URL of your own cluster. The tool never writes the credentials anywhere.

### 1. Device values per wave (hostname, management IP)

Central's bulk upload only works for switches that are already in new Central, with a site, device group and device
function. So set the values after moving or onboarding a wave. With a screen: the Onboarding tab. On the command line,
e.g. with a switch list from Classic (Devices, Switches, export):

```powershell
.\cnx.exe alias uit-classic-lijst --lijst export_switch_list.csv --prefix 24 --site-collection Belgium --out toestellen.csv
.\cnx.exe alias controleer --toestellen toestellen.csv
.\cnx.exe alias genereer --toestellen toestellen.csv --out uploads
```

Upload each file in `uploads` in new Central: Configuration, Library, Named Objects, Aliases, bulk upload. Check:
fetch a bulk download and compare.

```powershell
.\cnx.exe alias vergelijk --toestellen toestellen.csv --download bulk_alias_download_....csv
```

### 2. Imported VLAN descriptions to the library

A switch that moves from Classic gets its VLAN descriptions as local aliases. Because of that, a change on Global does
not apply to that switch.

```powershell
.\cnx.exe alias globaliseer --download bulk_alias_download_....csv --out globaal
.\cnx.exe api aanmaken --waarden globaal\2-global-waarden.csv --library --apply
.\cnx.exe api toewijzen --waarden globaal\2-global-waarden.csv --apply
.\cnx.exe api opkuisen --lijst globaal\3-opkuis-per-switch.csv --serial <SERIAL> --apply
```

First without `--apply` (dry run), and first with one switch. Every alias the toolkit creates through the API gets the
description "Alias aangemaakt via CNX API Tool". The bulk upload files have no column for the description, so aliases
from an upload through the UI do not get it.

### 3. VLANs from Global also to aggregation and core

```powershell
.\cnx.exe api vlans-doorzetten
.\cnx.exe api vlans-doorzetten --apply
```

Check in the dry run which VLANs and which switches are affected. Keep the log: you use it to roll back
(`vlans-terugdraaien --log ...`).

## Safety

- Everything that changes something in Central starts with a dry run or a plan. Only `--apply` on the command line or
  **Really remove** in the web app writes.
- Every change leaves a log (`.json`, with the tool's version number): as a download, and in the local app also in the
  working folder.
- After a change the tool reads back and reports differences.
- Central refuses to remove an alias or VLAN that something refers to. The tool reports that as "in use".
- How the toolkit handles data: see the [privacy statement](PRIVACY.md) (also in the app: `/privacy`) and
  [SECURITY.md](SECURITY.md).

## Limitations

- AOS-CX switches and Mobility Gateways (onboarding and overrides); access points only as analysis and plan for the
  move from AOS-8 to AOS-10.
- Central's bulk upload only updates existing aliases: it cannot create or remove them, and VSF stacks are not
  supported. Stacks go into `manueel-stacks.csv`.
- The new Central configuration API is v1alpha1: paths and fields can change. Test a new version of Central with a dry
  run first.
- The commands in the migration plan (steps marked *check*) have not yet been verified against HPE's migration guide.
- Use at your own risk. See LICENSE (Apache-2.0).

## Support

Report a problem on [GitHub](https://github.com/levicaers1-pixel/cnx-toolkit-web/issues), without customer data.
Mention the version number (`cnx --version`, or top left in the web app) and attach the log of the run. Report a
security problem privately (see [SECURITY.md](SECURITY.md)).
