-- ============================================================
-- Meridian Capital Partners - Stored Procedures
-- These are used by the old ASP.NET dashboard
--
-- Author: External consultant + Dave in ops
-- Modernized (SQL Server 2022 upgrade):
--   * Date parameters changed from VARCHAR(10) to native DATE
--   * sp_GetTrades cross-year bug fixed (real DATE comparison
--     instead of MM/DD/YYYY string comparison)
--   * Refreshed to current T-SQL string/date functions
-- ============================================================

-- Get all trades for a date range
-- Used by: Trade blotter screen, compliance team
CREATE OR ALTER PROCEDURE sp_GetTrades
    @StartDate DATE,
    @EndDate DATE,
    @AccountNumber VARCHAR(20) = NULL
AS
BEGIN
    SET NOCOUNT ON;

    -- TradeDate is now a real DATE, so range comparisons are correct
    -- across year boundaries (fixes JIRA-4521).
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
    ORDER BY TradeDate DESC, TradeID;
END
GO

-- Get portfolio summary for an account
-- Used by: Client portal, PM dashboard
CREATE OR ALTER PROCEDURE sp_GetPortfolioSummary
    @AccountNumber VARCHAR(20),
    @AsOfDate DATE = NULL
AS
BEGIN
    SET NOCOUNT ON;

    -- if no date specified, get latest
    IF @AsOfDate IS NULL
    BEGIN
        SELECT @AsOfDate = MAX(AsOfDate) FROM dbo.NAVHistory
        WHERE AccountNumber = @AccountNumber;
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
      AND n.AsOfDate = @AsOfDate;

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
        pr.ClosePrice AS CurrentPrice,
        pr.Volume
    FROM dbo.Positions p
    LEFT JOIN dbo.Prices pr ON p.Ticker = pr.Ticker AND p.AsOfDate = pr.PriceDate
    WHERE p.AccountNumber = @AccountNumber
      AND p.AsOfDate = @AsOfDate
      AND p.Quantity > 0
    ORDER BY p.MarketValue DESC;
END
GO

-- Get compliance violations
-- Used by: Compliance dashboard, monthly board reports
CREATE OR ALTER PROCEDURE sp_GetComplianceReport
    @StartDate DATE,
    @EndDate DATE,
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
        cv.AsOfDate DESC;
END
GO

-- Get reconciliation breaks
-- Used by: Ops team morning review
CREATE OR ALTER PROCEDURE sp_GetReconBreaks
    @AsOfDate DATE
AS
BEGIN
    SET NOCOUNT ON;

    -- PositionKey format is "ACCT|TICKER"; split into its two parts.
    SELECT
        r.PositionKey,
        r.Status,
        r.InternalQty,
        r.InternalValue,
        r.CustodianQty,
        r.CustodianValue,
        r.Detail,
        r.AsOfDate,
        LEFT(r.PositionKey, CHARINDEX('|', r.PositionKey) - 1) AS AccountNumber,
        SUBSTRING(r.PositionKey, CHARINDEX('|', r.PositionKey) + 1, 10) AS Ticker
    FROM dbo.ReconResults r
    WHERE r.AsOfDate = @AsOfDate
      AND r.Status <> 'MATCHED'
    ORDER BY
        CASE r.Status
            WHEN 'BREAK' THEN 1
            WHEN 'INTERNAL_ONLY' THEN 2
            WHEN 'CUSTODIAN_ONLY' THEN 3
            ELSE 4
        END;
END
GO

-- Firm-wide AUM report
-- Used by: Monthly board meeting, marketing
CREATE OR ALTER PROCEDURE sp_GetFirmAUM
    @AsOfDate DATE
AS
BEGIN
    SET NOCOUNT ON;

    -- total firm AUM
    SELECT
        SUM(TotalMarketValue) AS TotalAUM,
        COUNT(DISTINCT AccountNumber) AS TotalAccounts,
        SUM(EquityValue) AS TotalEquity,
        SUM(FIValue) AS TotalFixedIncome,
        AVG(ReturnPct) AS AvgReturn,
        SUM(DailyFee) * 365 AS EstAnnualRevenue
    FROM dbo.NAVHistory
    WHERE AsOfDate = @AsOfDate;

    -- AUM by PM
    SELECT
        PortfolioManager,
        COUNT(DISTINCT AccountNumber) AS Accounts,
        SUM(TotalMarketValue) AS AUM,
        AVG(ReturnPct) AS AvgReturn
    FROM dbo.NAVHistory
    WHERE AsOfDate = @AsOfDate
    GROUP BY PortfolioManager;

    -- AUM by client type
    SELECT
        c.ClientType,
        COUNT(DISTINCT n.AccountNumber) AS Accounts,
        SUM(n.TotalMarketValue) AS AUM
    FROM dbo.NAVHistory n
    LEFT JOIN dbo.Clients c ON n.AccountNumber = c.AccountNumber
    WHERE n.AsOfDate = @AsOfDate
    GROUP BY c.ClientType;
END
GO
