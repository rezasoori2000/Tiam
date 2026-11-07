"""Central place for environment-driven config, e.g. DB connection."""
import os
import urllib.parse

_ODBC_CONNECTION_STRING = (
    "Driver={ODBC Driver 17 for SQL Server};"
    r"Server=PGLHAM-ITLT03I\SQLEXPRESS1;"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
    # Not SecurityCamera: that's the factory/company system's DB, kept separate on purpose.
    "Database=RetailParkingMonitor;"
)

_DEFAULT_DATABASE_URL = (
    "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(_ODBC_CONNECTION_STRING)
)

DATABASE_URL = os.environ.get("SECURITYCAM_DATABASE_URL", _DEFAULT_DATABASE_URL)

# Azure Communication Services -- used to email incident snapshots from the
# Coaching Workbench. Set these two as real environment variables (never
# commit the connection string); leaving them unset just disables the
# feature with a clear error instead of crashing the app at startup.
AZURE_COMMUNICATION_CONNECTION_STRING = os.environ.get("AzureCommunicationServiceConnectionString")
AZURE_COMMUNICATION_SENDER_EMAIL = os.environ.get("AzureCommunicationServicesSenderEmail")
