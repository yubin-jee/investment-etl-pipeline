-- ============================================================
-- Meridian Capital Partners - Legacy Database Schema
-- Database: MeridianOMS (SQL Server 2022)
-- 
-- Original Author: External consultant (2017)
-- NOTE: No foreign keys were ever added because "it slowed
--       down the batch inserts" - Mike Torres, 2019
-- ============================================================

CREATE TABLE dbo.Clients (
    AccountNumber VARCHAR(20) NOT NULL,
    ClientName VARCHAR(200) NOT NULL,
    ClientType VARCHAR(50),
    TaxID VARCHAR(20),
    InceptionDate VARCHAR(10),  -- stored as string MM/DD/YYYY
    AUMTier VARCHAR(20),
    FeeSchedule VARCHAR(10),
    Benchmark VARCHAR(50),
    PortfolioManager VARCHAR(100),
    Status VARCHAR(20) DEFAULT 'ACTIVE',
    Address VARCHAR(500),
    City VARCHAR(100),
    State VARCHAR(2),
    ZipCode VARCHAR(10),
    Phone VARCHAR(20),
    Email VARCHAR(200),
    CreatedDate DATETIME DEFAULT GETDATE(),
    ModifiedDate DATETIME DEFAULT GETDATE(),
    -- no primary key constraint, just a note that AccountNumber should be unique
    -- Mike: "we check for dupes in the script"
);

CREATE TABLE dbo.Trades (
    TradeID VARCHAR(30),
    AccountNumber VARCHAR(20),
    Ticker VARCHAR(10),
    Side VARCHAR(4),
    Quantity INT,
    Price DECIMAL(18,4),
    GrossAmount DECIMAL(18,2),
    NetAmount DECIMAL(18,2),
    Commission DECIMAL(18,2),
    TradeDate VARCHAR(10),      -- MM/DD/YYYY format
    SettleDate VARCHAR(10),     -- MM/DD/YYYY format
    Broker VARCHAR(20),
    Status VARCHAR(20),
    ReconStatus VARCHAR(30),
    ProcessedAt DATETIME,
    CreatedDate DATETIME DEFAULT GETDATE()
    -- no indexes on this table
    -- query performance is "acceptable" per Mike
);

CREATE TABLE dbo.Positions (
    AccountNumber VARCHAR(20),
    Ticker VARCHAR(10),
    CUSIP VARCHAR(15),
    SEDOL VARCHAR(10),
    Quantity INT,
    AvgCost DECIMAL(18,4),
    MarketValue DECIMAL(18,2),
    UnrealizedPnL DECIMAL(18,2),
    AssetClass VARCHAR(30),
    Sector VARCHAR(50),
    AsOfDate VARCHAR(10),       -- MM/DD/YYYY format
    LoadedAt DATETIME DEFAULT GETDATE()
    -- no history table - positions are overwritten daily
    -- Lisa: "we should probably keep history" (2021)
);

CREATE TABLE dbo.Prices (
    Ticker VARCHAR(10),
    PriceDate VARCHAR(10),      -- MM/DD/YYYY format
    OpenPrice DECIMAL(18,4),
    HighPrice DECIMAL(18,4),
    LowPrice DECIMAL(18,4),
    ClosePrice DECIMAL(18,4),
    Volume BIGINT,
    AdjClose DECIMAL(18,4),
    Source VARCHAR(20),
    LoadedAt DATETIME DEFAULT GETDATE()
    -- prices are bulk loaded daily via BCP
    -- old prices are never cleaned up
);

CREATE TABLE dbo.NAVHistory (
    AccountNumber VARCHAR(20),
    ClientName VARCHAR(200),
    TotalMarketValue DECIMAL(18,2),
    CostBasis DECIMAL(18,2),
    UnrealizedPnL DECIMAL(18,2),
    ReturnPct DECIMAL(18,4),
    PositionCount INT,
    EquityValue DECIMAL(18,2),
    FIValue DECIMAL(18,2),
    EquityPct DECIMAL(18,4),
    FIPct DECIMAL(18,4),
    DailyFee DECIMAL(18,4),
    PortfolioManager VARCHAR(100),
    Benchmark VARCHAR(50),
    AsOfDate VARCHAR(10),
    GeneratedAt DATETIME,
    LoadedAt DATETIME DEFAULT GETDATE()
);

CREATE TABLE dbo.ComplianceViolations (
    RuleID VARCHAR(20),
    Severity VARCHAR(20),
    AccountNumber VARCHAR(20),
    ClientName VARCHAR(200),
    Detail VARCHAR(500),
    Value DECIMAL(18,4),
    Action VARCHAR(30),
    AsOfDate VARCHAR(10),
    GeneratedAt DATETIME,
    ResolvedDate DATETIME NULL,
    ResolvedBy VARCHAR(100) NULL,
    Notes VARCHAR(1000) NULL,
    LoadedAt DATETIME DEFAULT GETDATE()
);

CREATE TABLE dbo.ReconResults (
    PositionKey VARCHAR(50),
    Status VARCHAR(30),
    InternalQty INT,
    InternalValue DECIMAL(18,2),
    CustodianQty INT,
    CustodianValue DECIMAL(18,2),
    Detail VARCHAR(500),
    AsOfDate VARCHAR(10),
    GeneratedAt DATETIME,
    LoadedAt DATETIME DEFAULT GETDATE()
);

-- ============================================================
-- "Indexes" added by Dave in ops after complaints about slow queries
-- ============================================================
-- CREATE INDEX IX_Trades_Date ON dbo.Trades (TradeDate);
-- ^ commented out because it made the nightly load take too long

-- CREATE INDEX IX_Positions_Account ON dbo.Positions (AccountNumber);
-- ^ this one is fine, uncomment if you want

GO
