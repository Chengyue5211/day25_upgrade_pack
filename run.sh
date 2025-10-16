#!/usr/bin/env bash
set -e
export UPG25_DB=${UPG25_DB:-upgrade25.sqlite3}
uvicorn app.main:app --reload --port 8000
