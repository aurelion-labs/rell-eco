RELL WORKLOAD TRACKER
====================
Version 1.0  |  Internal Use Only


HOW TO USE
----------
1. Double-click JOSEFINA_START_HERE.bat
   (First time only: it will install the required software automatically — takes about a minute)

2. Your browser will open automatically showing the Workload Tracker.

3. Drag your Workload Tracker Excel file onto the upload area,
   or click the area to browse for the file.

4. Click "Analyze Workload".

5. Review the results. The three team tables show:
   - US DATA ANALYST WORKLOAD    (your team)
   - PHILIPPINES DA WORKLOAD     (Auie's team)
   - DATA QUALITY SPECIALIST WORKLOAD

6. Click "⬇ Export PDF" to download a printable report.


UNDERSTANDING THE RESULTS
--------------------------
Load badges per analyst:
  OVR  = OVERLOADED  — more than 25% above team average
  OK   = BALANCED    — within normal range
  LOW  = UNDERLOADED — more than 25% below team average

"Dev vs Avg" column shows how much above (+) or below (-) the team average.

Analysts shown below the dotted separator have flags:
  [partial]  — Incomplete data in this spreadsheet
  [departed] — Has left the company
  [x-collab] — Cross-team collaborator (shown for visibility)
  [biz-ops]  — Not a DA/DQS role


UPDATING THE TEAM ROSTER
-------------------------
When someone joins, leaves, or changes their name:
1. Open the file:  config\team-roster.json
2. Edit the appropriate section (add or remove the name)
3. Names must match EXACTLY as they appear in the Excel
4. Save the file and restart the app

For married name changes, update the "name_aliases" section:
  "Old Name": "New Full Name"


REQUIREMENTS
------------
- Windows 10 or later
- Python 3.11 or later (free: https://www.python.org/downloads/)
- An internet connection for first-time setup only


GETTING UPDATES
---------------
When there is a new version, you will receive either:
  A)  A new zip file — extract it over your existing folder
  B)  A message to run: git pull  (if you have Git installed)

After updating, restart the app normally.


SUPPORT
-------
Contact: Chase Key
