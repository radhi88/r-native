# AI Geometric Agentic Desk — Report (2026-06-26 04:40 UTC)

- Magic: `20260626` | LIVE_TRADING=False | DEMO_ONLY=True | REQUIRE_EXAM_PASS=False
- Gates: exam >= 95.0, PF >= 2.5

## Model & Geometry Architecture

- **ML**: dependency-free logistic regression, 5 causal features (momentum/vol ratio, volatility, bar range, body, range position), trained per-window; confidence gate = 55%.
- **RL**: linear Q-learning over the same 5 features, 3 actions (flat/long/short), net-R reward.
- **Confluence**: trade when >= 2 signals align.
- **Sizing**: modified Kelly (cap 0.15), ATR stop, survival reject > 15% min-lot risk.

### Per-market Gann/Sq9 settings

- gold: Sq9[180, 360, 720] R=1.5 k=2.0 emphasis=smc+ob+fvg+sq9_360
- forex: Sq9[90, 180, 360] R=1.5 k=1.6 emphasis=smc+ob+fvg+sq9_90_180
- indices: Sq9[90, 180, 360] R=2.0 k=1.8 emphasis=bos+choch+vwap+gann_1x1
- crypto: Sq9[180, 360, 720] R=1.5 k=1.8 emphasis=vp+footprint+fractal
- stocks: Sq9[90, 180, 360] R=1.5 k=1.5 emphasis=ob+daily_fvg

## Latest Walk-Forward Exam Scores

| Symbol | Score | PF | Trades | WinRate | Exp(R) | Notes |
|---|---|---|---|---|---|---|
| BTCJPYm | 37.5 | 0.83 | 102 | 39% | -0.101 | HR retake#1 pf=0.83 wr=39% exp=-0.101R n=102 folds+=2/4 |
| BTCUSDm | 43.6 | 0.91 | 85 | 44% | -0.049 | HR retake#1 pf=0.91 wr=44% exp=-0.049R n=85 folds+=3/4 |
| ETHUSDm | 25.5 | 0.54 | 95 | 35% | -0.294 | HR retake#1 pf=0.54 wr=35% exp=-0.294R n=95 folds+=1/4 |
| BTCUSDTm | 37.3 | 0.91 | 84 | 45% | -0.045 | HR retake#1 pf=0.91 wr=45% exp=-0.045R n=84 folds+=2/4 |
| ETHBTCm | 26.6 | 0.64 | 88 | 42% | -0.241 | HR retake#1 pf=0.64 wr=42% exp=-0.241R n=88 folds+=1/4 |
| DKKPLNm | 7.4 | 0.00 | 74 | 0% | -20.694 | HR retake#1 pf=0.00 wr=0% exp=-20.694R n=74 folds+=0/4 |
| UKOILm | 29.3 | 0.80 | 86 | 40% | -0.125 | HR retake#1 pf=0.80 wr=40% exp=-0.125R n=86 folds+=1/4 |
| USOILm | 19.2 | 0.62 | 81 | 32% | -0.278 | HR retake#1 pf=0.62 wr=32% exp=-0.278R n=81 folds+=0/4 |
| XNGUSDm | 8.6 | 0.05 | 76 | 14% | -1.693 | HR retake#1 pf=0.05 wr=14% exp=-1.693R n=76 folds+=0/4 |
| CHFSGDm | 7.8 | 0.00 | 78 | 0% | -2.624 | HR retake#1 pf=0.00 wr=0% exp=-2.624R n=78 folds+=0/4 |
| CHFZARm | 7.3 | 0.02 | 69 | 10% | -1.971 | HR retake#1 pf=0.02 wr=10% exp=-1.971R n=69 folds+=0/4 |
| DKKJPYm | 6.0 | 0.00 | 60 | 0% | -2.693 | HR retake#1 pf=0.00 wr=0% exp=-2.693R n=60 folds+=0/4 |
| DKKSGDm | 10.0 | 0.00 | 119 | 0% | -7.263 | HR retake#1 pf=0.00 wr=0% exp=-7.263R n=119 folds+=0/4 |
| DKKZARm | 9.8 | 0.02 | 94 | 16% | -2.041 | HR retake#1 pf=0.02 wr=16% exp=-2.041R n=94 folds+=0/4 |
| DXYm | 33.8 | 0.67 | 92 | 46% | -0.234 | HR retake#1 pf=0.67 wr=46% exp=-0.234R n=92 folds+=2/4 |
| EURAUDm | 21.7 | 0.38 | 87 | 26% | -0.554 | HR retake#1 pf=0.38 wr=26% exp=-0.554R n=87 folds+=1/4 |
| EURCADm | 32.1 | 0.84 | 45 | 49% | -0.112 | HR retake#1 pf=0.84 wr=49% exp=-0.112R n=45 folds+=2/4 |
| EURCHFm | 22.8 | 0.36 | 118 | 47% | -0.526 | HR retake#1 pf=0.36 wr=47% exp=-0.526R n=118 folds+=1/4 |
| EURDKKm | 9.0 | 0.00 | 90 | 0% | -152.835 | HR retake#1 pf=0.00 wr=0% exp=-152.835R n=90 folds+=0/4 |
| EURGBPm | 21.1 | 0.53 | 53 | 51% | -0.380 | HR retake#1 pf=0.53 wr=51% exp=-0.380R n=53 folds+=1/4 |
| EURJPYm | 47.3 | 1.12 | 80 | 55% | +0.065 | HR retake#1 pf=1.12 wr=55% exp=+0.065R n=80 folds+=2/4 |
| EURMXNm | 10.2 | 0.01 | 100 | 5% | -2.213 | HR retake#1 pf=0.01 wr=5% exp=-2.213R n=100 folds+=0/4 |
| EURNOKm | 7.3 | 0.00 | 73 | 0% | -4.128 | HR retake#1 pf=0.00 wr=0% exp=-4.128R n=73 folds+=0/4 |
| EURNZDm | 24.6 | 0.55 | 84 | 38% | -0.339 | HR retake#1 pf=0.55 wr=38% exp=-0.339R n=84 folds+=1/4 |
| EURPLNm | 10.0 | 0.00 | 122 | 0% | -16.154 | HR retake#1 pf=0.00 wr=0% exp=-16.154R n=122 folds+=0/4 |
| EURSGDm | 7.6 | 0.01 | 74 | 7% | -1.834 | HR retake#1 pf=0.01 wr=7% exp=-1.834R n=74 folds+=0/4 |
| EURUSDm | 26.6 | 0.58 | 158 | 34% | -0.311 | HR retake#1 pf=0.58 wr=34% exp=-0.311R n=158 folds+=1/4 |
| EURZARm | 8.3 | 0.02 | 79 | 15% | -1.648 | HR retake#1 pf=0.02 wr=15% exp=-1.648R n=79 folds+=0/4 |
| GBPAUDm | 24.5 | 0.53 | 87 | 34% | -0.367 | HR retake#1 pf=0.53 wr=34% exp=-0.367R n=87 folds+=1/4 |
| GBPCADm | 20.8 | 0.40 | 74 | 28% | -0.490 | HR retake#1 pf=0.40 wr=28% exp=-0.490R n=74 folds+=1/4 |
| GBPCHFm | 9.3 | 0.14 | 68 | 16% | -0.887 | HR retake#1 pf=0.14 wr=16% exp=-0.887R n=68 folds+=0/4 |
| GBPDKKm | 9.6 | 0.00 | 96 | 0% | -4.755 | HR retake#1 pf=0.00 wr=0% exp=-4.755R n=96 folds+=0/4 |
| GBPILSm | 11.8 | 0.10 | 112 | 30% | -1.148 | HR retake#1 pf=0.10 wr=30% exp=-1.148R n=112 folds+=0/4 |
| GBPJPYm | 25.4 | 0.57 | 89 | 36% | -0.313 | HR retake#1 pf=0.57 wr=36% exp=-0.313R n=89 folds+=1/4 |
| GBPMXNm | 8.4 | 0.03 | 78 | 24% | -1.592 | HR retake#1 pf=0.03 wr=24% exp=-1.592R n=78 folds+=0/4 |
| GBPNOKm | 10.1 | 0.00 | 102 | 4% | -3.936 | HR retake#1 pf=0.00 wr=4% exp=-3.936R n=102 folds+=0/4 |
| GBPNZDm | 16.6 | 0.37 | 106 | 30% | -0.558 | HR retake#1 pf=0.37 wr=30% exp=-0.558R n=106 folds+=0/4 |
| GBPSEKm | 10.2 | 0.01 | 117 | 9% | -2.881 | HR retake#1 pf=0.01 wr=9% exp=-2.881R n=117 folds+=0/4 |
| GBPSGDm | 6.8 | 0.00 | 68 | 0% | -5.118 | HR retake#1 pf=0.00 wr=0% exp=-5.118R n=68 folds+=0/4 |
| GBPUSDm | 23.2 | 0.40 | 98 | 27% | -0.471 | HR retake#1 pf=0.40 wr=27% exp=-0.471R n=98 folds+=1/4 |
| GBPZARm | 10.6 | 0.06 | 95 | 17% | -1.505 | HR retake#1 pf=0.06 wr=17% exp=-1.505R n=95 folds+=0/4 |
| HKDJPYm | 5.0 | 0.00 | 50 | 0% | -5.071 | HR retake#1 pf=0.00 wr=0% exp=-5.071R n=50 folds+=0/4 |
| MXNJPYm | 10.8 | 0.04 | 106 | 18% | -1.907 | HR retake#1 pf=0.04 wr=18% exp=-1.907R n=106 folds+=0/4 |
| NOKDKKm | 6.8 | 0.00 | 68 | 1% | -5.987 | HR retake#1 pf=0.00 wr=1% exp=-5.987R n=68 folds+=0/4 |
| NOKJPYm | 7.4 | 0.00 | 74 | 0% | -3.387 | HR retake#1 pf=0.00 wr=0% exp=-3.387R n=74 folds+=0/4 |
| NOKSEKm | 10.0 | 0.00 | 133 | 1% | -6.391 | HR retake#1 pf=0.00 wr=1% exp=-6.391R n=133 folds+=0/4 |
| NZDCADm | 12.9 | 0.28 | 78 | 36% | -0.736 | HR retake#1 pf=0.28 wr=36% exp=-0.736R n=78 folds+=0/4 |
| NZDCHFm | 23.2 | 0.43 | 91 | 47% | -0.445 | HR retake#1 pf=0.43 wr=47% exp=-0.445R n=91 folds+=1/4 |
| NZDDKKm | 2.8 | 0.00 | 28 | 0% | -4.137 | HR retake#1 pf=0.00 wr=0% exp=-4.137R n=28 folds+=0/4 |
| NZDJPYm | 39.6 | 0.95 | 109 | 50% | -0.030 | HR retake#1 pf=0.95 wr=50% exp=-0.030R n=109 folds+=2/4 |
| NZDMXNm | 5.3 | 0.09 | 38 | 26% | -1.280 | HR retake#1 pf=0.09 wr=26% exp=-1.280R n=38 folds+=0/4 |
| NZDNOKm | 7.3 | 0.00 | 73 | 1% | -3.659 | HR retake#1 pf=0.00 wr=1% exp=-3.659R n=73 folds+=0/4 |
| NZDSEKm | 8.8 | 0.00 | 88 | 0% | -2.894 | HR retake#1 pf=0.00 wr=0% exp=-2.894R n=88 folds+=0/4 |
| NZDSGDm | 5.2 | 0.00 | 52 | 4% | -2.806 | HR retake#1 pf=0.00 wr=4% exp=-2.806R n=52 folds+=0/4 |
| NZDUSDm | 27.7 | 0.77 | 76 | 54% | -0.154 | HR retake#1 pf=0.77 wr=54% exp=-0.154R n=76 folds+=1/4 |
| NZDZARm | 9.3 | 0.00 | 93 | 4% | -1.972 | HR retake#1 pf=0.00 wr=4% exp=-1.972R n=93 folds+=0/4 |
| SEKDKKm | 8.5 | 0.00 | 85 | 0% | -5.796 | HR retake#1 pf=0.00 wr=0% exp=-5.796R n=85 folds+=0/4 |
| SEKJPYm | 7.7 | 0.00 | 77 | 1% | -2.191 | HR retake#1 pf=0.00 wr=1% exp=-2.191R n=77 folds+=0/4 |
| SGDHKDm | 6.1 | 0.00 | 61 | 0% | -5.018 | HR retake#1 pf=0.00 wr=0% exp=-5.018R n=61 folds+=0/4 |
| SGDJPYm | 10.1 | 0.00 | 117 | 6% | -2.128 | HR retake#1 pf=0.00 wr=6% exp=-2.128R n=117 folds+=0/4 |
| USDCADm | 38.4 | 0.88 | 124 | 49% | -0.077 | HR retake#1 pf=0.88 wr=49% exp=-0.077R n=124 folds+=2/4 |
| USDCHFm | 21.3 | 0.43 | 74 | 36% | -0.467 | HR retake#1 pf=0.43 wr=36% exp=-0.467R n=74 folds+=1/4 |
| USDCNHm | 6.8 | 0.00 | 68 | 1% | -4.417 | HR retake#1 pf=0.00 wr=1% exp=-4.417R n=68 folds+=0/4 |
| USDDKKm | 10.2 | 0.01 | 139 | 7% | -2.531 | HR retake#1 pf=0.01 wr=7% exp=-2.531R n=139 folds+=0/4 |
| USDHKDm | 10.0 | 0.00 | 103 | 0% | -23.729 | HR retake#1 pf=0.00 wr=0% exp=-23.729R n=103 folds+=0/4 |
| USDILSm | 13.4 | 0.19 | 99 | 43% | -0.851 | HR retake#1 pf=0.19 wr=43% exp=-0.851R n=99 folds+=0/4 |
| USDJPYm | 8.0 | 0.17 | 49 | 14% | -0.835 | HR retake#1 pf=0.17 wr=14% exp=-0.835R n=49 folds+=0/4 |
| USDMXNm | 7.7 | 0.08 | 63 | 29% | -1.541 | HR retake#1 pf=0.08 wr=29% exp=-1.541R n=63 folds+=0/4 |
| USDNOKm | 8.6 | 0.00 | 85 | 2% | -3.140 | HR retake#1 pf=0.00 wr=2% exp=-3.140R n=85 folds+=0/4 |
| USDSEKm | 10.4 | 0.02 | 119 | 12% | -1.822 | HR retake#1 pf=0.02 wr=12% exp=-1.822R n=119 folds+=0/4 |
| USDSGDm | 8.4 | 0.00 | 84 | 0% | -3.817 | HR retake#1 pf=0.00 wr=0% exp=-3.817R n=84 folds+=0/4 |
| USDZARm | 11.1 | 0.06 | 102 | 19% | -1.323 | HR retake#1 pf=0.06 wr=19% exp=-1.323R n=102 folds+=0/4 |
| XAUUSDm | 13.9 | 0.29 | 88 | 25% | -0.480 | pf=0.29 wr=25% exp=-0.480R n=88 folds+=0/4 |
| XAGAUDm | 44.9 | 1.19 | 83 | 52% | +0.089 | HR retake#1 pf=1.19 wr=52% exp=+0.089R n=83 folds+=1/4 |

## Executed Trade Journal

| Symbol | Entry | SL dist | Kelly f | Confluences | Time |
|---|---|---|---|---|---|
| BTCUSDTm | 59421.27 | 431.42143 | 0.150 | SMC BOS + ML 57% | 2026-06-26T03:41:47.127154+00:00 |
| BTCUSDm | 59338.9 | 434.70000 | 0.150 | SMC BOS + ML 58% | 2026-06-26T03:41:46.606541+00:00 |
| BTCUSDTm | 59361.76 | 440.33400 | 0.150 | Bear-Fractal + ML 55% | 2026-06-26T03:38:24.715467+00:00 |
| BTCUSDm | 58654.92 | 552.29014 | 0.150 | Bear-Fractal + Sq9 -180deg + ML 55% | 2026-06-26T03:09:34.460898+00:00 |
| BTCUSDm | 58483.22 | 497.21786 | 0.000 | Bear-Fractal + Sq9 -360deg + ML 58% | 2026-06-26T02:59:39.742921+00:00 |
| BTCUSDm | 58462.56 | 478.24200 | 0.000 | Bear-Fractal + Sq9 -360deg + ML 57% | 2026-06-26T02:55:11.449098+00:00 |
| BTCUSDm | 58462.89 | 361.46571 | 0.000 | SMC BOS + Bear-Fractal + ML 60% | 2026-06-26T02:25:33.567020+00:00 |
| BTCUSDm | 58296.22 | 357.72171 | 0.000 | SMC BOS + Bear-Fractal + ML 59% | 2026-06-26T02:24:25.001841+00:00 |
| BTCUSDm | 58329.09 | 351.78943 | 0.000 | SMC BOS + Bear-Fractal + ML 58% | 2026-06-26T02:23:01.683682+00:00 |
| BTCUSDm | 58397.3 | 351.78943 | 0.000 | SMC BOS + Bear-Fractal + ML 59% | 2026-06-26T02:21:43.035705+00:00 |
| BTCUSDm | 58566.67 | 332.43814 | 0.000 | SMC BOS + Bear-Fractal + Sq9 -360deg + ML 62% | 2026-06-26T02:19:15.035497+00:00 |
| TSLAm | 373.94 | 1.32457 | 0.150 | Bear-Fractal + ML 57% | 2026-06-26T04:09:03.839456+00:00 |
| AAPLm | 275.3 | 1.47429 | 0.150 | SMC BOS + ML 58% | 2026-06-26T04:08:57.889396+00:00 |
| DE30m | 24831.2 | 34.41143 | 0.150 | Bear-Fractal + ML 61% | 2026-06-26T04:08:55.683792+00:00 |
| USOILm | 70.347 | 0.16389 | 0.150 | SMC BOS + Bear-Fractal + ML 56% | 2026-06-26T04:08:49.586078+00:00 |
| TSLAm | 373.94 | 1.32457 | 0.150 | Bear-Fractal + ML 57% | 2026-06-26T03:51:08.124963+00:00 |
| AAPLm | 275.3 | 1.47429 | 0.150 | SMC BOS + ML 58% | 2026-06-26T03:51:01.722881+00:00 |
| USOILm | 70.419 | 0.16846 | 0.150 | SMC BOS + Bear-Fractal + ML 57% | 2026-06-26T03:50:49.294295+00:00 |
| TSLAm | 373.94 | 1.32457 | 0.150 | Bear-Fractal + ML 57% | 2026-06-26T03:47:45.366122+00:00 |
| AAPLm | 275.3 | 1.47429 | 0.150 | SMC BOS + ML 58% | 2026-06-26T03:47:38.780458+00:00 |
| USOILm | 70.406 | 0.17486 | 0.150 | SMC BOS + Bear-Fractal + ML 60% | 2026-06-26T03:47:23.485967+00:00 |
| TSLAm | 373.94 | 1.32457 | 0.150 | Bear-Fractal + ML 57% | 2026-06-26T03:44:20.126108+00:00 |
| AAPLm | 275.3 | 1.47429 | 0.150 | SMC BOS + ML 58% | 2026-06-26T03:44:13.778184+00:00 |
| USOILm | 70.481 | 0.17577 | 0.150 | SMC BOS + Bear-Fractal + ML 57% | 2026-06-26T03:44:07.626552+00:00 |
| TSLAm | 373.94 | 1.32457 | 0.150 | Bear-Fractal + ML 57% | 2026-06-26T03:42:02.598943+00:00 |
| AAPLm | 275.3 | 1.47429 | 0.150 | SMC BOS + ML 58% | 2026-06-26T03:41:56.591250+00:00 |
| USOILm | 70.482 | 0.17554 | 0.150 | SMC BOS + Bear-Fractal + ML 57% | 2026-06-26T03:41:47.739732+00:00 |
| TSLAm | 373.94 | 1.32457 | 0.150 | Bear-Fractal + ML 57% | 2026-06-26T03:38:29.614458+00:00 |
| AAPLm | 275.3 | 1.47429 | 0.150 | SMC BOS + ML 58% | 2026-06-26T03:38:27.771626+00:00 |
| TSLAm | 373.94 | 1.32457 | 0.150 | Bear-Fractal + ML 57% | 2026-06-26T03:18:09.675932+00:00 |
| AAPLm | 275.3 | 1.47429 | 0.150 | SMC BOS + ML 58% | 2026-06-26T03:18:06.714409+00:00 |
| ZTOm | 21.66 | 0.02857 | 0.150 | Bear-Fractal + ML 64% | 2026-06-26T03:10:41.639665+00:00 |
| YUMCm | 40.16 | 0.05486 | 0.150 | SMC BOS + Bear-Fractal + ML 62% | 2026-06-26T03:10:39.973134+00:00 |
| TSMm | 461.86 | 1.67543 | 0.150 | SMC BOS + Bull-Fractal + ML 59% | 2026-06-26T03:10:37.986864+00:00 |
| PDDm | 73.6 | 0.13714 | 0.150 | Bear-Fractal + ML 60% | 2026-06-26T03:10:36.255344+00:00 |
| NTESm | 114.97 | 0.12114 | 0.150 | SMC BOS + ML 58% | 2026-06-26T03:10:34.206384+00:00 |
| NIOm | 4.75 | 0.00571 | 0.150 | SMC BOS + ML 86% | 2026-06-26T03:10:32.496019+00:00 |
| JDm | 25.17 | 0.08457 | 0.150 | Bear-Fractal + ML 60% | 2026-06-26T03:10:31.077837+00:00 |
| FUTUm | 98.17 | 0.23200 | 0.150 | SMC sweep + Liq-Sweep + ML 57% | 2026-06-26T03:10:29.670308+00:00 |
| FTNTm | 150.18 | 0.51657 | 0.150 | SMC BOS + ML 59% | 2026-06-26T03:10:28.261364+00:00 |
| EDUm | 43.89 | 0.07429 | 0.150 | SMC BOS + ML 61% | 2026-06-26T03:10:26.457161+00:00 |
| BILIm | 16.16 | 0.02857 | 0.150 | SMC sweep + Liq-Sweep + Bear-Fractal + ML 67% | 2026-06-26T03:10:25.189447+00:00 |
| BIDUm | 103.64 | 0.24343 | 0.150 | Bear-Fractal + ML 65% | 2026-06-26T03:10:23.697242+00:00 |
| BEKEm | 14.24 | 0.01943 | 0.150 | Bear-Fractal + ML 64% | 2026-06-26T03:10:22.341724+00:00 |
| VZm | 45.61 | 0.08229 | 0.150 | SMC BOS + ML 57% | 2026-06-26T03:10:19.844404+00:00 |
| UPSm | 108.46 | 0.24571 | 0.150 | Bear-Fractal + ML 58% | 2026-06-26T03:10:18.191647+00:00 |
| TSLAm | 373.94 | 1.32457 | 0.150 | Bear-Fractal + ML 57% | 2026-06-26T03:10:16.892104+00:00 |
| Tm | 22.34 | 0.04229 | 0.150 | Bear-Fractal + ML 55% | 2026-06-26T03:10:15.813274+00:00 |
| PGm | 148.4 | 0.37943 | 0.150 | Bear-Fractal + ML 55% | 2026-06-26T03:10:14.161544+00:00 |
| PFEm | 23.55 | 0.05143 | 0.150 | SMC BOS + Bear-Fractal + ML 66% | 2026-06-26T03:10:12.227719+00:00 |
| PEPm | 139.63 | 0.27543 | 0.150 | Bear-Fractal + ML 57% | 2026-06-26T03:10:10.853584+00:00 |
| ORCLm | 152.29 | 0.81029 | 0.150 | Bear-Fractal + ML 56% | 2026-06-26T03:10:09.401825+00:00 |
| NKEm | 40.67 | 0.11886 | 0.150 | Bear-Fractal + ML 61% | 2026-06-26T03:10:08.055394+00:00 |
| NFLXm | 71.35 | 0.24571 | 0.150 | SMC BOS + Bear-Fractal + ML 58% | 2026-06-26T03:10:06.016933+00:00 |
| MMMm | 167.35 | 0.32114 | 0.150 | SMC sweep + Liq-Sweep + Bear-Fractal + ML 60% | 2026-06-26T03:10:04.032623+00:00 |
| MDLZm | 60.93 | 0.15314 | 0.150 | SMC BOS + Bear-Fractal + ML 56% | 2026-06-26T03:10:03.230180+00:00 |
| LLYm | 1128.09 | 4.15086 | 0.150 | SMC BOS + ML 55% | 2026-06-26T03:10:02.402649+00:00 |
| JNJm | 245.57 | 0.51429 | 0.150 | SMC sweep + Liq-Sweep + ML 59% | 2026-06-26T03:10:01.557033+00:00 |
| HDm | 343.65 | 0.88114 | 0.150 | SMC sweep + Liq-Sweep + ML 56% | 2026-06-26T03:10:00.192392+00:00 |
| GOOGLm | 341.81 | 1.32571 | 0.150 | Bull-Fractal + ML 62% | 2026-06-26T03:09:59.508145+00:00 |
| METAm | 544.12 | 1.64229 | 0.150 | Bull-Fractal + ML 58% | 2026-06-26T03:09:58.775458+00:00 |
