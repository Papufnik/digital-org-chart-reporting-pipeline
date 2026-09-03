"""
build_sample_data.py -- generates the illustrative dashboard_app/*.json
fixtures this repo's Senior Manager / CEO scripts read from, so a reviewer
can clone this repo and run the pipeline end-to-end with `python demo.py`
against realistic-but-fabricated numbers, no real business data required.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "dashboard_app")
os.makedirs(OUT, exist_ok=True)


def write(name, data):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"wrote {name}")


write("gmroi_live.json", {"overall": 6.35})

write("cash_forecast_live.json", {
    "conservativeCaseDecCash": 68920.14,
    "baseCaseDecCash": 91340.50,
    "growthTrendPct": 0.084,
    "ttmBaseRevenue": 1142300.00,
})

write("phantom_inventory_live.json", {
    "deadStockCost": 52140.75,
    "deadStockCount": 1048,
})

write("weekly_budget_model.json", {"recommendedAllowance": 9410.50})

write("pos_data_mining_insights.json", {
    "dataAvailable": True,
    "crossSellMetrics": {
        "topAttachmentPairs": [
            {
                "primaryCategory": "Outerwear",
                "attachedCategory": "Accessories",
                "attachmentRatePct": 34.2,
                "ordersWithBoth": 118,
                "ordersWithPrimary": 345,
            }
        ],
    },
})

write("wholesale_ap_schedule.json", {
    "totalWholesaleAP": 23660.90,
    "totalSource": "Sum of open wholesale marketplace orders not yet charged",
    "reconciliationNote": "Matches the wholesale marketplace's own AP dashboard as of last sync.",
})

write("mca_payoff_live.json", {
    "currentBalance": 39275.60,
    "weeklyPayment": 1180.40,
})

write("inventory_velocity_live.json", {
    "deadStockCost": 52140.75,
    "deadStockCount": 1048,
    "missedSales30Days": 54830.25,
    "oosDemandCount": 212,
})

write("stockout_alerts_live.json", {
    "totalMonitoredSKUs": 2150,
    "atRiskStockoutSKUs": 617,
    "urgentStockouts": [
        {"sku": "SKU-1042", "estimatedPOCost": 340.00},
        {"sku": "SKU-2213", "estimatedPOCost": 512.50},
        {"sku": "SKU-3390", "estimatedPOCost": 220.00},
    ] * 7,  # 21 illustrative rows, ~$5.5K combined
})

write("markdown_optimization_live.json", {
    "totalSlowMovingSKUs": 998,
    "totalCapitalTiedUp": 63110.80,
})

write("vendor_roi_live.json", {
    "overallMarkup": 2.18,
    "isProxyMetric": True,
    "bottomVendors": [
        {"name": "Vendor A", "markup": 1.32},
        {"name": "Vendor B", "markup": 1.44},
    ],
})

write("margin_erosion_alerts.json", {
    "totalAlerts": 6,
    "asOfDate": "",  # left blank so the demo shows the staleness-flag behavior
    "topAnomalies": [
        {"sku": "SKU-4471", "cost_increase_amt": 1.85},
        {"sku": "SKU-5502", "cost_increase_amt": 0.90},
    ],
})

write("labor_efficiency_live.json", {
    "overtimeRatePct": 4.1,
    "monthlyLaborPct": [
        {"month": "Jul '25", "netSales": 210000, "labor": 39900, "laborPct": 0.19},
        {"month": "Aug '25", "netSales": 198000, "labor": 41580, "laborPct": 0.21},
        {"month": "Jul '26", "netSales": 224000, "labor": 47040, "laborPct": 0.21},
        {"month": "Aug '26 (MTD thru 8/9)", "netSales": 61000, "labor": 14030, "laborPct": 0.23},
    ],
})

write("petty_cash_analysis_live.json", {
    "unreconciledGap": 480.25,
    "ledgerGapFlag": "$480.25 of staff-reported petty cash spend isn't yet traceable to a bank transaction.",
})

write("tourist_weather_forecast_live.json", {
    "sevenDayForecast": [
        {"date": "2026-09-04", "trafficIndex": 1.4, "staffingRecommendation": "Normal staffing"},
        {"date": "2026-09-05", "trafficIndex": 2.1, "staffingRecommendation": "SURGE -- add one floor associate"},
        {"date": "2026-09-06", "trafficIndex": 2.3, "staffingRecommendation": "SURGE -- add one floor associate"},
    ],
})

write("discount_elasticity_live.json", {
    "overallDiscountRatePct": 8.4,
    "correlation": 0.06,
    "topCategoriesByDiscountRate": [
        {"category": "Seasonal Clearance", "discount": 22.0, "gross": 14200, "ratePct": 22.0},
    ],
})

write("pos_payout_fee_audit_live.json", {
    "last30DaysMetrics": {"blendedFeeRatePct": 2.71},
    "anomalies": [],
    "feeAlertThresholdPct": 3.0,
})

write("bank_pos_reconciliation_live.json", {
    "matchRatePct": 98.7,
    "totalPosNetPayouts": 389450.60,
    "totalPosUnmatched": 0.0,
    "totalBankUnmatched": 16720.30,
    "posExportWindow": {"start": "2026-07-01", "end": "2026-08-31"},
    "posExportStale": False,
})

print("\nDONE -- sample dashboard_app/ fixtures written.")

