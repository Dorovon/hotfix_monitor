# Hotfix Monitor
This is a simple script to locally monitor hotfixes for World of Warcraft. This supports versions 7 and 8 of the DBCache.bin file format, which has been in use since Battle for Azeroth.

## Usage
- This script monitors your local DBCache.bin files for changes and prints out basic details for each new entry that was detected (Push IDs, table names, and Record IDs).
- The purpose of this script is to alert you that records in a table changed and not to display the specific content of those records, which is better handled by a full DB2 parser that supports hotfixes.
  - While DBCache.bin also contains binary data for new/modified records, the specific format of this data can vary for each table and build.
  - This data is often not very useful without also tracking the original DB2 data that was present prior to any hotfixes for the build.
- The dictionary near the beginning of hotfix_monitor.py may need to be modified depending on where you have World of Warcraft installed and which versions of the game you are interested in monitoring.
- Optionally, a "webhooks" file can be created, which will additionally post the detected changes to the Discord channel corresponding to the Webhook link on each line.
