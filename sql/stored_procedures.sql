-- ============================================================
-- Meridian Capital Partners - Stored Procedures
-- These are used by the old ASP.NET dashboard
-- 
-- Author: External consultant + Dave in ops
-- WARNING: sp_GetPortfolioSummary has a known bug where it
--          double-counts positions if run before the nightly
--          position load completes. Nobody has fixed this
--          because "it usually works fine."
-- ============================================================

-- Get all trades for a date range
-- Used by: Trade blotter screen, compliance team
-- Fixed: now uses proper DATE parameters and comparison (JIRA-4521).
-- Requires migration 001_modernize_trades_schema.sql (TradeDate is DATE).
CREATE PROCEDURE sp_GetTrades
    @StartDate DATE,
    @EndDate DATE,
    @AccountNumber VARCHAR(20) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    
    SELECT 
        TradeID,
        AccountNumber,
        Ticker,
        Side,
        Quantity,
        Price,
        GrossAmount,
        NetAmount,
        Commission,
        TradeDate,
        SettleDate,
        Broker,
        Status,
        ReconStatus,
        ProcessedAt
    FROM dbo.Trades
    WHERE TradeDate >= @StartDate 
      AND TradeDate <= @EndDate
      AND (@AccountNumber IS NULL OR AccountNumber = @AccountNumber)
    ORDER BY TradeDate DESC, TradeID
END
GO

-- Get portfolio summary for an account
-- Used by: Client portal, PM dashboard
CREATE PROCEDURE sp_GetPortfolioSummary
    @AccountNumber VARCHAR(20),
    @AsOfDate VARCHAR(10) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    
    -- if no date specified, get latest
    IF @AsOfDate IS NULL
    BEGIN
        SELECT @AsOfDate = MAX(AsOfDate) FROM dbo.NAVHistory 
        WHERE AccountNumber = @AccountNumber
    END
    
    -- NAV summary
    SELECT 
        n.AccountNumber,
        n.ClientName,
        n.TotalMarketValue,
        n.CostBasis,
        n.UnrealizedPnL,
        n.ReturnPct,
        n.PositionCount,
        n.EquityPct,
        n.FIPct,
        n.DailyFee,
        n.PortfolioManager,
        n.Benchmark,
        n.AsOfDate,
        c.ClientType,
        c.InceptionDate
    FROM dbo.NAVHistory n
    LEFT JOIN dbo.Clients c ON n.AccountNumber = c.AccountNumber
    WHERE n.AccountNumber = @AccountNumber
      AND n.AsOfDate = @AsOfDate
    
    -- Position detail
    SELECT 
        p.Ticker,
        p.CUSIP,
        p.Quantity,
        p.AvgCost,
        p.MarketValue,
        p.UnrealizedPnL,
        p.AssetClass,
        p.Sector,
        pr.ClosePrice as CurrentPrice,
        pr.Volume
    FROM dbo.Positions p
    LEFT JOIN dbo.Prices pr ON p.Ticker = pr.Ticker AND p.AsOfDate = pr.PriceDate
    WHERE p.AccountNumber = @AccountNumber
      AND p.AsOfDate = @AsOfDate
      AND p.Quantity > 0
    ORDER BY p.MarketValue DESC
END
GO

-- Get compliance violations
-- Used by: Compliance dashboard, monthly board reports
CREATE PROCEDURE sp_GetComplianceReport
    @StartDate VARCHAR(10),
    @EndDate VARCHAR(10),
    @Severity VARCHAR(20) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    
    SELECT 
        cv.RuleID,
        cv.Severity,
        cv.AccountNumber,
        cv.ClientName,
        cv.Detail,
        cv.Value,
        cv.Action,
        cv.AsOfDate,
        cv.ResolvedDate,
        cv.ResolvedBy,
        cv.Notes,
        c.PortfolioManager
    FROM dbo.ComplianceViolations cv
    LEFT JOIN dbo.Clients c ON cv.AccountNumber = c.AccountNumber
    WHERE cv.AsOfDate >= @StartDate 
      AND cv.AsOfDate <= @EndDate
      AND (@Severity IS NULL OR cv.Severity = @Severity)
    ORDER BY 
        CASE cv.Severity 
            WHEN 'CRITICAL' THEN 1 
            WHEN 'HIGH' THEN 2 
            WHEN 'MEDIUM' THEN 3 
            WHEN 'LOW' THEN 4 
            ELSE 5 
        END,
        cv.AsOfDate DESC
END
GO

-- Get reconciliation breaks
-- Used by: Ops team morning review
CREATE PROCEDURE sp_GetReconBreaks
    @AsOfDate VARCHAR(10)
AS
BEGIN
    SET NOCOUNT ON;
    
    SELECT 
        r.PositionKey,
        r.Status,
        r.InternalQty,
        r.InternalValue,
        r.CustodianQty,
        r.CustodianValue,
        r.Detail,
        r.AsOfDate,
        -- try to get account and ticker from the key
        -- key format is "ACCT|TICKER"
        LEFT(r.PositionKey, CHARINDEX('|', r.PositionKey) - 1) as AccountNumber,
        SUBSTRING(r.PositionKey, CHARINDEX('|', r.PositionKey) + 1, 10) as Ticker
    FROM dbo.ReconResults r
    WHERE r.AsOfDate = @AsOfDate
      AND r.Status <> 'MATCHED'
    ORDER BY 
        CASE r.Status
            WHEN 'BREAK' THEN 1
            WHEN 'INTERNAL_ONLY' THEN 2
            WHEN 'CUSTODIAN_ONLY' THEN 3
            ELSE 4
        END
END
GO

-- Firm-wide AUM report
-- Used by: Monthly board meeting, marketing
CREATE PROCEDURE sp_GetFirmAUM
    @AsOfDate VARCHAR(10)
AS
BEGIN
    SET NOCOUNT ON;
    
    -- total firm AUM
    SELECT 
        SUM(TotalMarketValue) as TotalAUM,
        COUNT(DISTINCT AccountNumber) as TotalAccounts,
        SUM(EquityValue) as TotalEquity,
        SUM(FIValue) as TotalFixedIncome,
        AVG(ReturnPct) as AvgReturn,
        SUM(DailyFee) * 365 as EstAnnualRevenue
    FROM dbo.NAVHistory
    WHERE AsOfDate = @AsOfDate
    
    -- AUM by PM
    SELECT 
        PortfolioManager,
        COUNT(DISTINCT AccountNumber) as Accounts,
        SUM(TotalMarketValue) as AUM,
        AVG(ReturnPct) as AvgReturn
    FROM dbo.NAVHistory
    WHERE AsOfDate = @AsOfDate
    GROUP BY PortfolioManager
    
    -- AUM by client type
    SELECT 
        c.ClientType,
        COUNT(DISTINCT n.AccountNumber) as Accounts,
        SUM(n.TotalMarketValue) as AUM
    FROM dbo.NAVHistory n
    LEFT JOIN dbo.Clients c ON n.AccountNumber = c.AccountNumber
    WHERE n.AsOfDate = @AsOfDate
    GROUP BY c.ClientType
END
GO
