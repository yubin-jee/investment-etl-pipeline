-- ============================================================
-- Meridian Capital Partners - Database Schema
-- Database: MeridianOMS (SQL Server 2022)
--
-- Original Author: External consultant (2017)
-- Modernized (2022 upgrade):
--   * String MM/DD/YYYY date columns converted to native DATE
--   * Primary keys, foreign keys, and nonclustered indexes added
--   * Positions converted to a system-versioned temporal table
--     (SCD Type 2 position history) per the migration objectives
--   * Native JSON metadata columns guarded with ISJSON constraints
-- ============================================================

-- ------------------------------------------------------------
-- Clients
-- ------------------------------------------------------------
CREATE TABLE dbo.Clients (
    AccountNumber VARCHAR(20) NOT NULL,
    ClientName VARCHAR(200) NOT NULL,
    ClientType VARCHAR(50),
    TaxID VARCHAR(20),
    InceptionDate DATE,
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
    -- Native JSON document for flexible client attributes (SQL Server 2022)
    Metadata NVARCHAR(MAX) NULL,
    CreatedDate DATETIME2(3) DEFAULT SYSUTCDATETIME(),
    ModifiedDate DATETIME2(3) DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_Clients PRIMARY KEY (AccountNumber),
    CONSTRAINT CK_Clients_Metadata_JSON CHECK (Metadata IS NULL OR ISJSON(Metadata) = 1)
);
GO

-- ------------------------------------------------------------
-- Trades
-- ------------------------------------------------------------
CREATE TABLE dbo.Trades (
    TradeID VARCHAR(30) NOT NULL,
    AccountNumber VARCHAR(20) NOT NULL,
    Ticker VARCHAR(10),
    Side VARCHAR(4),
    Quantity INT,
    Price DECIMAL(18,4),
    GrossAmount DECIMAL(18,2),
    NetAmount DECIMAL(18,2),
    Commission DECIMAL(18,2),
    TradeDate DATE,
    SettleDate DATE,
    Broker VARCHAR(20),
    Status VARCHAR(20),
    ReconStatus VARCHAR(30),
    ProcessedAt DATETIME2(3),
    CreatedDate DATETIME2(3) DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_Trades PRIMARY KEY (TradeID),
    CONSTRAINT FK_Trades_Clients FOREIGN KEY (AccountNumber)
        REFERENCES dbo.Clients (AccountNumber)
);
GO

CREATE NONCLUSTERED INDEX IX_Trades_TradeDate ON dbo.Trades (TradeDate) INCLUDE (AccountNumber);
CREATE NONCLUSTERED INDEX IX_Trades_Account ON dbo.Trades (AccountNumber, TradeDate);
GO

-- ------------------------------------------------------------
-- Positions  (system-versioned temporal table = SCD Type 2 history)
-- ------------------------------------------------------------
CREATE TABLE dbo.Positions (
    AccountNumber VARCHAR(20) NOT NULL,
    Ticker VARCHAR(10) NOT NULL,
    CUSIP VARCHAR(15),
    SEDOL VARCHAR(10),
    Quantity INT,
    AvgCost DECIMAL(18,4),
    MarketValue DECIMAL(18,2),
    UnrealizedPnL DECIMAL(18,2),
    AssetClass VARCHAR(30),
    Sector VARCHAR(50),
    AsOfDate DATE,
    LoadedAt DATETIME2(3) DEFAULT SYSUTCDATETIME(),
    ValidFrom DATETIME2(3) GENERATED ALWAYS AS ROW START HIDDEN NOT NULL,
    ValidTo DATETIME2(3) GENERATED ALWAYS AS ROW END HIDDEN NOT NULL,
    PERIOD FOR SYSTEM_TIME (ValidFrom, ValidTo),
    CONSTRAINT PK_Positions PRIMARY KEY (AccountNumber, Ticker),
    CONSTRAINT FK_Positions_Clients FOREIGN KEY (AccountNumber)
        REFERENCES dbo.Clients (AccountNumber)
)
WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = dbo.PositionsHistory));
GO

CREATE NONCLUSTERED INDEX IX_Positions_Account ON dbo.Positions (AccountNumber);
CREATE NONCLUSTERED INDEX IX_Positions_AsOfDate ON dbo.Positions (AsOfDate);
GO

-- ------------------------------------------------------------
-- Prices
-- ------------------------------------------------------------
CREATE TABLE dbo.Prices (
    Ticker VARCHAR(10) NOT NULL,
    PriceDate DATE NOT NULL,
    OpenPrice DECIMAL(18,4),
    HighPrice DECIMAL(18,4),
    LowPrice DECIMAL(18,4),
    ClosePrice DECIMAL(18,4),
    Volume BIGINT,
    AdjClose DECIMAL(18,4),
    Source VARCHAR(20),
    LoadedAt DATETIME2(3) DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_Prices PRIMARY KEY (Ticker, PriceDate)
);
GO

CREATE NONCLUSTERED INDEX IX_Prices_PriceDate ON dbo.Prices (PriceDate);
GO

-- ------------------------------------------------------------
-- NAVHistory
-- ------------------------------------------------------------
CREATE TABLE dbo.NAVHistory (
    AccountNumber VARCHAR(20) NOT NULL,
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
    AsOfDate DATE NOT NULL,
    GeneratedAt DATETIME2(3),
    LoadedAt DATETIME2(3) DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_NAVHistory PRIMARY KEY (AccountNumber, AsOfDate),
    CONSTRAINT FK_NAVHistory_Clients FOREIGN KEY (AccountNumber)
        REFERENCES dbo.Clients (AccountNumber)
);
GO

CREATE NONCLUSTERED INDEX IX_NAVHistory_AsOfDate ON dbo.NAVHistory (AsOfDate);
GO

-- ------------------------------------------------------------
-- ComplianceViolations
-- ------------------------------------------------------------
CREATE TABLE dbo.ComplianceViolations (
    ViolationID BIGINT IDENTITY(1,1) NOT NULL,
    RuleID VARCHAR(20),
    Severity VARCHAR(20),
    AccountNumber VARCHAR(20),
    ClientName VARCHAR(200),
    Detail VARCHAR(500),
    Value DECIMAL(18,4),
    Action VARCHAR(30),
    AsOfDate DATE,
    GeneratedAt DATETIME2(3),
    ResolvedDate DATETIME2(3) NULL,
    ResolvedBy VARCHAR(100) NULL,
    Notes VARCHAR(1000) NULL,
    LoadedAt DATETIME2(3) DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ComplianceViolations PRIMARY KEY (ViolationID)
);
GO

CREATE NONCLUSTERED INDEX IX_ComplianceViolations_AsOfDate
    ON dbo.ComplianceViolations (AsOfDate) INCLUDE (Severity, AccountNumber);
GO

-- ------------------------------------------------------------
-- ReconResults
-- ------------------------------------------------------------
CREATE TABLE dbo.ReconResults (
    ReconID BIGINT IDENTITY(1,1) NOT NULL,
    PositionKey VARCHAR(50),
    Status VARCHAR(30),
    InternalQty INT,
    InternalValue DECIMAL(18,2),
    CustodianQty INT,
    CustodianValue DECIMAL(18,2),
    Detail VARCHAR(500),
    AsOfDate DATE,
    GeneratedAt DATETIME2(3),
    LoadedAt DATETIME2(3) DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ReconResults PRIMARY KEY (ReconID)
);
GO

CREATE NONCLUSTERED INDEX IX_ReconResults_AsOfDate
    ON dbo.ReconResults (AsOfDate) INCLUDE (Status);
GO
