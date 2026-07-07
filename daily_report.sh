#!/bin/bash
RANGE="${1:-today}"
case "$RANGE" in
  today)     SINCE="6am";           UNTIL="now";  LABEL="Today ($(date '+%A, %B %-d'))" ;;
  yesterday) SINCE="yesterday 6am";  UNTIL="6am";  LABEL="Yesterday" ;;
  week)      SINCE="7 days ago";     UNTIL="now";  LABEL="Last 7 Days" ;;
  *) echo "Use: today | yesterday | week"; exit 1 ;;
esac
echo ""
echo "=================================================="
echo "  POINKLE CODE REPORT - $LABEL"
echo "=================================================="
echo ""
COMMIT_COUNT=$(git log --since="$SINCE" --until="$UNTIL" --oneline | wc -l | tr -d ' ')
if [ "$COMMIT_COUNT" -eq 0 ]; then
  echo "  No commits in this period."
  echo "  (Only committed work is counted.)"
  echo "=================================================="; echo ""; exit 0
fi
echo "  COMMITS ($COMMIT_COUNT):"
git log --since="$SINCE" --until="$UNTIL" --pretty="  %h  %s"
echo ""
git log --since="$SINCE" --until="$UNTIL" --numstat --pretty="%H" \
  | awk 'NF==3 && $1 ~ /^[0-9]+$/ { add+=$1; del+=$2 }
      END { printf "  --------------------------------------------\n  Lines added:   %d\n  Lines removed: %d\n  Net change:    %+d\n", add, del, add-del }'
echo "=================================================="
echo ""
