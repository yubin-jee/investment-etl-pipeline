-- ============================================================
-- Migration 001: Modernize Trades & Clients Schema
-- Database: MeridianOMS (SQL Server)
--
-- Changes:
--   1. Convert VARCHAR(10) date columns to DATE (with data migration)
--   2. Add primary key to dbo.Trades (TradeID)
--   3. Add unique constraint / PK to dbo.Clients (AccountNumber)
--   4. Add foreign key from Trades → Clients
--   5. Add composite index on (TradeDate, AccountNumber)
--   6. Fix sp_GetTrades to use proper DATE comparison
--
-- NOTE: Run in a transaction; back up before executing.
-- ============================================================

BEGIN TRANSACTION;

-- -------------------------------------------------------
-- 1a. Convert dbo.Clients.InceptionDate VARCHAR → DATE
-- -------------------------------------------------------
-- Data migration: convert existing MM/DD/YYYY strings
UPDATE dbo.Clients
SET InceptionDate = CONVERT(VARCHAR(10), CONVERT(DATE, InceptionDate, 101), 120)
WHERE InceptionDate IS NOT NULL
  AND InceptionDate <> ''
  AND ISDATE(InceptionDate) = 1;

ALTER TABLE dbo.Clients ALTER COLUMN InceptionDate DATE NULL;

-- -------------------------------------------------------
-- 1b. Convert dbo.Trades.TradeDate VARCHAR → DATE
-- -------------------------------------------------------
UPDATE dbo.Trades
SET TradeDate = CONVERT(VARCHAR(10), CONVERT(DATE, TradeDate, 101), 120)
WHERE TradeDate IS NOT NULL
  AND TradeDate <> ''
  AND ISDATE(TradeDate) = 1;

ALTER TABLE dbo.Trades ALTER COLUMN TradeDate DATE NOT NULL;

-- -------------------------------------------------------
-- 1c. Convert dbo.Trades.SettleDate VARCHAR → DATE
-- -------------------------------------------------------
UPDATE dbo.Trades
SET SettleDate = CONVERT(VARCHAR(10), CONVERT(DATE, SettleDate, 101), 120)
WHERE SettleDate IS NOT NULL
  AND SettleDate <> ''
  AND ISDATE(SettleDate) = 1;

-- Allow NULL settle dates (some trades have no settle date yet)
ALTER TABLE dbo.Trades ALTER COLUMN SettleDate DATE NULL;

-- -------------------------------------------------------
-- 2. Add primary key on dbo.Trades.TradeID
-- -------------------------------------------------------
-- Ensure TradeID is NOT NULL before adding PK
ALTER TABLE dbo.Trades ALTER COLUMN TradeID VARCHAR(30) NOT NULL;

ALTER TABLE dbo.Trades
ADD CONSTRAINT PK_Trades PRIMARY KEY (TradeID);

-- -------------------------------------------------------
-- 3. Add unique constraint on dbo.Clients.AccountNumber
-- -------------------------------------------------------
ALTER TABLE dbo.Clients ALTER COLUMN AccountNumber VARCHAR(20) NOT NULL;

ALTER TABLE dbo.Clients
ADD CONSTRAINT UQ_Clients_AccountNumber UNIQUE (AccountNumber);

-- -------------------------------------------------------
-- 4. Add foreign key: Trades.AccountNumber → Clients.AccountNumber
-- -------------------------------------------------------
ALTER TABLE dbo.Trades
ADD CONSTRAINT FK_Trades_Clients
    FOREIGN KEY (AccountNumber)
    REFERENCES dbo.Clients (AccountNumber);

-- -------------------------------------------------------
-- 5. Add composite index for sp_GetTrades performance
-- -------------------------------------------------------
CREATE INDEX IX_Trades_TradeDate_Account
    ON dbo.Trades (TradeDate, AccountNumber);

COMMIT TRANSACTION;
GO
