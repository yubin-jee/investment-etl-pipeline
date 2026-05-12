-- ============================================================
-- Migration 002: Clean DDL — Modernized Schema (fresh installs)
-- Database: MeridianOMS (SQL Server)
--
-- This script creates the tables from scratch with the updated
-- schema.  Use for new deployments; existing databases should
-- apply 001_modernize_trades_schema.sql instead.
-- ============================================================

-- -------------------------------------------------------
-- Clients
-- -------------------------------------------------------
CREATE TABLE dbo.Clients (
    AccountNumber   VARCHAR(20)   NOT NULL,
    ClientName      VARCHAR(200)  NOT NULL,
    ClientType      VARCHAR(50)   NULL,
    TaxID           VARCHAR(20)   NULL,
    InceptionDate   DATE          NULL,
    AUMTier         VARCHAR(20)   NULL,
    FeeSchedule     VARCHAR(10)   NULL,
    Benchmark       VARCHAR(50)   NULL,
    PortfolioManager VARCHAR(100) NULL,
    Status          VARCHAR(20)   NOT NULL DEFAULT 'ACTIVE',
    Address         VARCHAR(500)  NULL,
    City            VARCHAR(100)  NULL,
    State           VARCHAR(2)    NULL,
    ZipCode         VARCHAR(10)   NULL,
    Phone           VARCHAR(20)   NULL,
    Email           VARCHAR(200)  NULL,
    CreatedDate     DATETIME      NOT NULL DEFAULT GETDATE(),
    ModifiedDate    DATETIME      NOT NULL DEFAULT GETDATE(),

    CONSTRAINT PK_Clients PRIMARY KEY (AccountNumber)
);

-- -------------------------------------------------------
-- Trades
-- -------------------------------------------------------
CREATE TABLE dbo.Trades (
    TradeID         VARCHAR(30)    NOT NULL,
    AccountNumber   VARCHAR(20)    NOT NULL,
    Ticker          VARCHAR(10)    NOT NULL,
    Side            VARCHAR(4)     NOT NULL,
    Quantity        INT            NOT NULL,
    Price           DECIMAL(18,4)  NOT NULL,
    GrossAmount     DECIMAL(18,2)  NULL,
    NetAmount       DECIMAL(18,2)  NULL,
    Commission      DECIMAL(18,2)  NULL,
    TradeDate       DATE           NOT NULL,
    SettleDate      DATE           NULL,
    Broker          VARCHAR(20)    NULL,
    Status          VARCHAR(20)    NULL,
    ReconStatus     VARCHAR(30)    NULL,
    ProcessedAt     DATETIME       NULL,
    CreatedDate     DATETIME       NOT NULL DEFAULT GETDATE(),

    CONSTRAINT PK_Trades PRIMARY KEY (TradeID),
    CONSTRAINT FK_Trades_Clients FOREIGN KEY (AccountNumber)
        REFERENCES dbo.Clients (AccountNumber)
);

CREATE INDEX IX_Trades_TradeDate_Account
    ON dbo.Trades (TradeDate, AccountNumber);

-- -------------------------------------------------------
-- Positions
-- -------------------------------------------------------
CREATE TABLE dbo.Positions (
    AccountNumber   VARCHAR(20)    NOT NULL,
    Ticker          VARCHAR(10)    NOT NULL,
    CUSIP           VARCHAR(15)    NULL,
    SEDOL           VARCHAR(10)    NULL,
    Quantity        INT            NULL,
    AvgCost         DECIMAL(18,4)  NULL,
    MarketValue     DECIMAL(18,2)  NULL,
    UnrealizedPnL   DECIMAL(18,2)  NULL,
    AssetClass      VARCHAR(30)    NULL,
    Sector          VARCHAR(50)    NULL,
    AsOfDate        DATE           NULL,
    LoadedAt        DATETIME       NOT NULL DEFAULT GETDATE()
);

CREATE INDEX IX_Positions_Account ON dbo.Positions (AccountNumber);

-- -------------------------------------------------------
-- Prices
-- -------------------------------------------------------
CREATE TABLE dbo.Prices (
    Ticker          VARCHAR(10)    NOT NULL,
    PriceDate       DATE           NOT NULL,
    OpenPrice       DECIMAL(18,4)  NULL,
    HighPrice       DECIMAL(18,4)  NULL,
    LowPrice        DECIMAL(18,4)  NULL,
    ClosePrice      DECIMAL(18,4)  NULL,
    Volume          BIGINT         NULL,
    AdjClose        DECIMAL(18,4)  NULL,
    Source          VARCHAR(20)    NULL,
    LoadedAt        DATETIME       NOT NULL DEFAULT GETDATE()
);

-- -------------------------------------------------------
-- NAV History
-- -------------------------------------------------------
CREATE TABLE dbo.NAVHistory (
    AccountNumber       VARCHAR(20)    NOT NULL,
    ClientName          VARCHAR(200)   NULL,
    TotalMarketValue    DECIMAL(18,2)  NULL,
    CostBasis           DECIMAL(18,2)  NULL,
    UnrealizedPnL       DECIMAL(18,2)  NULL,
    ReturnPct           DECIMAL(18,4)  NULL,
    PositionCount       INT            NULL,
    EquityValue         DECIMAL(18,2)  NULL,
    FIValue             DECIMAL(18,2)  NULL,
    EquityPct           DECIMAL(18,4)  NULL,
    FIPct               DECIMAL(18,4)  NULL,
    DailyFee            DECIMAL(18,4)  NULL,
    PortfolioManager    VARCHAR(100)   NULL,
    Benchmark           VARCHAR(50)    NULL,
    AsOfDate            DATE           NULL,
    GeneratedAt         DATETIME       NULL,
    LoadedAt            DATETIME       NOT NULL DEFAULT GETDATE()
);

-- -------------------------------------------------------
-- Compliance Violations
-- -------------------------------------------------------
CREATE TABLE dbo.ComplianceViolations (
    RuleID          VARCHAR(20)    NULL,
    Severity        VARCHAR(20)    NULL,
    AccountNumber   VARCHAR(20)    NULL,
    ClientName      VARCHAR(200)   NULL,
    Detail          VARCHAR(500)   NULL,
    Value           DECIMAL(18,4)  NULL,
    Action          VARCHAR(30)    NULL,
    AsOfDate        DATE           NULL,
    GeneratedAt     DATETIME       NULL,
    ResolvedDate    DATETIME       NULL,
    ResolvedBy      VARCHAR(100)   NULL,
    Notes           VARCHAR(1000)  NULL,
    LoadedAt        DATETIME       NOT NULL DEFAULT GETDATE()
);

-- -------------------------------------------------------
-- Reconciliation Results
-- -------------------------------------------------------
CREATE TABLE dbo.ReconResults (
    PositionKey     VARCHAR(50)    NULL,
    Status          VARCHAR(30)    NULL,
    InternalQty     INT            NULL,
    InternalValue   DECIMAL(18,2)  NULL,
    CustodianQty    INT            NULL,
    CustodianValue  DECIMAL(18,2)  NULL,
    Detail          VARCHAR(500)   NULL,
    AsOfDate        DATE           NULL,
    GeneratedAt     DATETIME       NULL,
    LoadedAt        DATETIME       NOT NULL DEFAULT GETDATE()
);

GO
