"""Reproducible analysis of time_series_example.csv; run from the repo root."""
from __future__ import annotations

import json, warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import statsmodels.api as sm
from arch.unitroot import PhillipsPerron
from docx import Document
from docx.shared import Inches, Pt
from scipy import stats
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.stats.stattools import jarque_bera
from statsmodels.tsa.ar_model import AutoReg
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.holtwinters import Holt, SimpleExpSmoothing
from statsmodels.tsa.stattools import adfuller, kpss, acf, zivot_andrews

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "time_series_example.csv"
OUT = ROOT / "analysis_outputs" / "comprehensive_time_series"
FIG = OUT / "figures"
TAB = OUT / "tables"
YCOL = "Unemployment_Rate"
XCOLS = ["Synthetic_Inflation_Rate", "Synthetic_GDP_Growth", "Synthetic_Wage_Index", "Synthetic_Policy_Rate"]
NUMERIC = [YCOL, *XCOLS]
BLUE, RED, TEAL, ORANGE, PURPLE = "#2457A7", "#B8423C", "#16817A", "#C66A13", "#7653A6"


def setup():
    sns.set_theme(style="whitegrid", context="notebook", font="DejaVu Sans", rc={
        "axes.spines.top": False, "axes.spines.right": False, "grid.color": "#D9DEE7",
        "grid.alpha": .7, "grid.linewidth": .6, "axes.labelsize": 10,
        "axes.titlesize": 12, "figure.titlesize": 14, "savefig.dpi": 300,
    })
    FIG.mkdir(parents=True, exist_ok=True); TAB.mkdir(parents=True, exist_ok=True)


def validate():
    d = pd.read_csv(SOURCE)
    d["Year"] = pd.to_numeric(d.Year, errors="raise").astype(int)
    for c in NUMERIC: d[c] = pd.to_numeric(d[c], errors="raise")
    assert len(d) == 35 and (d.Year.min(), d.Year.max()) == (1991, 2025)
    assert d.Year.is_monotonic_increasing and d.Year.is_unique and not d.isna().any().any()
    assert d.Year.tolist() == list(range(1991, 2026))
    v = {"n": len(d), "start": int(d.Year.min()), "end": int(d.Year.max()),
         "annual": True, "chronological": True, "missing": 0, "duplicate_years": 0,
         "synthetic_predictors": XCOLS, "unemployment_source": "Not specified in the supplied CSV."}
    (OUT / "validation.json").write_text(json.dumps(v, indent=2), encoding="utf-8")
    return d, v


def descriptives(d):
    rows = []
    for c in NUMERIC:
        x = d[c]; q1, q3 = x.quantile([.25, .75]); changes = x.diff().dropna()
        growth = x.pct_change().replace([np.inf, -np.inf], np.nan).dropna() * 100
        rows.append({"Variable": c, "N": x.count(), "Mean": x.mean(), "Median": x.median(),
            "Minimum": x.min(), "Maximum": x.max(), "Range": x.max()-x.min(),
            "Variance": x.var(ddof=1), "Standard deviation": x.std(ddof=1),
            "Skewness": x.skew(), "Excess kurtosis": x.kurt(),
            "Mean absolute annual change": changes.abs().mean(), "Mean annual growth (%)": growth.mean(),
            "IQR outlier years": ", ".join(map(str, d.loc[(x < q1-1.5*(q3-q1)) | (x > q3+1.5*(q3-q1)), "Year"].tolist())) or "None"})
    out = pd.DataFrame(rows); out.to_csv(TAB/"descriptive_statistics.csv", index=False); return out


def axis_style(ax, date=False):
    from matplotlib.ticker import FuncFormatter, MaxNLocator
    def fmt(x, _):
        return f"{x:,.2f}".rstrip("0").rstrip(".") if abs(x) >= 1 else f"{x:.3f}".rstrip("0").rstrip(".")
    ax.yaxis.set_major_locator(MaxNLocator(6)); ax.yaxis.set_major_formatter(FuncFormatter(fmt))
    ax.tick_params(labelsize=9); ax.grid(axis="x", alpha=.3)
    if date:
        locator=mdates.YearLocator(5); ax.xaxis.set_major_locator(locator); ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def save(fig, name):
    p=FIG/name; fig.tight_layout(); fig.savefig(p,dpi=300,bbox_inches="tight",facecolor="white"); plt.close(fig); return p


def explore_graphs(d):
    files={}; dates=pd.to_datetime(d.Year.astype(str)+"-01-01")
    for c in NUMERIC:
        label=c.replace("_"," "); unit="index points" if "Index" in c else "%"
        fig,ax=plt.subplots(figsize=(9,4.7)); ax.plot(dates,d[c],color=BLUE,lw=2,marker="o",ms=3,label="Observed")
        t=np.arange(len(d),dtype=float); fit=sm.OLS(d[c],sm.add_constant(t)).fit()
        ax.plot(dates,fit.fittedvalues,color=RED,lw=1.7,ls="--",label="Fitted linear trend")
        ax.plot(dates,d[c].rolling(3,min_periods=1).mean(),color=TEAL,lw=1.8,label="Trailing 3-year mean")
        title=("Annual Unemployment Rate and Linear Trend (1991–2025)" if c==YCOL else f"{label}: Annual Series, Linear Trend, and Moving Average")
        ax.set_title(title); ax.set_xlabel("Year"); ax.set_ylabel(f"{label} ({unit})"); ax.legend(frameon=False,fontsize=8); axis_style(ax,True)
        if c==YCOL: ax.set_xlim(pd.Timestamp("1991-01-01"),pd.Timestamp("2025-12-31"))
        files[c+"_series"]=save(fig,c.lower()+"_series.png")
        fig,axs=plt.subplots(1,2,figsize=(9,4.2),gridspec_kw={"width_ratios":[3,1]})
        sns.histplot(d[c],bins="auto",kde=True,color=TEAL,ax=axs[0]); axs[0].set_title(f"{label}: Distribution"); axs[0].set_xlabel(f"{label} ({unit})"); axs[0].set_ylabel("Frequency (observations)")
        sns.boxplot(y=d[c],color="#C8D8F0",width=.45,ax=axs[1]); axs[1].set_title("Box plot"); axs[1].set_xlabel("Variable"); axs[1].set_ylabel(f"{label} ({unit})"); axs[1].set_xticks([0],[label])
        for a in axs: axis_style(a)
        files[c+"_distribution"]=save(fig,c.lower()+"_distribution.png")
    corr=d[NUMERIC].corr(); corr.to_csv(TAB/"correlation_matrix.csv")
    fig,ax=plt.subplots(figsize=(8,6)); sns.heatmap(corr,annot=True,fmt=".2f",cmap="vlag",vmin=-1,vmax=1,center=0,square=True,cbar_kws={"label":"Pearson correlation coefficient"},ax=ax)
    ax.set_title("Pearson Correlations Among Numeric Variables"); ax.set_xlabel("Variable"); ax.set_ylabel("Variable"); files["heatmap"]=save(fig,"correlation_heatmap.png")
    fig,ax=plt.subplots(figsize=(9,4.7)); ax.plot(d.Year,d[YCOL].diff(),color=BLUE,lw=1.8,marker="o",ms=3); ax.axhline(0,color="#555",lw=.8)
    ax.set_title("Unemployment Rate: Annual First Differences"); ax.set_xlabel("Year"); ax.set_ylabel("Annual change (percentage points)"); axis_style(ax); files["first_difference"]=save(fig,"unemployment_first_difference.png")
    from statsmodels.tsa.stattools import pacf
    fig,axs=plt.subplots(1,2,figsize=(9,4.3)); vals=d[YCOL].to_numpy(float); band=1.96/np.sqrt(len(vals))
    for ax,corr,title,color in ((axs[0],acf(vals,nlags=12,fft=False),"Unemployment Rate: ACF",BLUE),(axs[1],pacf(vals,nlags=12,method="ywm"),"Unemployment Rate: PACF",TEAL)):
        ax.bar(np.arange(len(corr)),corr,color=color,width=.72); ax.axhspan(-band,band,color="#687386",alpha=.12,label="Approximate 95% bounds"); ax.axhline(0,color="#555",lw=.8)
        ax.set_title(title); ax.set_xlabel("Lag (years)"); ax.set_ylabel("Correlation"); ax.legend(frameon=False,fontsize=8)
    files["acf_pacf"]=save(fig,"unemployment_acf_pacf.png")
    return files


def stationarity(y):
    rows=[]
    for phase,x in (("Level",y),("First difference",y.diff().dropna())):
        for det,detlabel in (("c","Constant"),("ct","Constant + trend")):
            for name in ("ADF","PP","KPSS"):
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        if name=="ADF":
                            r=adfuller(x,regression=det,autolag="AIC"); stat,p,crit=r[0],r[1],r[4]; null="unit root"
                        elif name=="PP":
                            r=PhillipsPerron(x,trend=det); stat,p,crit=r.stat,r.pvalue,r.critical_values; null="unit root"
                        else:
                            r=kpss(x,regression=det,nlags="auto"); stat,p,crit=r[0],r[1],r[3]; null="stationarity"
                    rows.append({"Series":phase,"Deterministic":detlabel,"Test":name,"Statistic":stat,"P-value":p,"Null":null,"Alternative":"stationary" if null=="unit root" else "nonstationary",**{f"Critical {k}":v for k,v in crit.items()}})
                except Exception as e: rows.append({"Series":phase,"Deterministic":detlabel,"Test":name,"Error":str(e)})
    out=pd.DataFrame(rows)
    for alpha in (.01,.05,.10):
        def decision(row):
            p=row.get("P-value",np.nan)
            if pd.isna(p): return "Unavailable"
            rejected=float(p)<alpha
            if row["Test"]=="KPSS": return "Reject stationarity" if rejected else "Fail to reject stationarity"
            return "Reject unit root" if rejected else "Fail to reject unit root"
        out[f"Decision at {alpha:.0%}"]=out.apply(decision,axis=1)
    out.to_csv(TAB/"stationarity.csv",index=False)
    return out


def breaks(d):
    y=d[YCOL].to_numpy(); years=d.Year.to_numpy(); t=years-years.min(); base=sm.OLS(y,sm.add_constant(t)).fit(); rows=[]
    for yr in (2008,2009,2015,2019,2020,2021):
        left=years<yr; n0=int(left.sum()); n1=len(y)-n0
        if min(n0,n1)<8: rows.append({"Year":yr,"Method":"Chow joint level/slope","Status":"Not tested: fewer than 8 observations in a segment"}); continue
        sse=0
        for mask in (left,~left): sse+=sm.OLS(y[mask],sm.add_constant(years[mask]-years[mask].min())).fit().ssr
        df2=len(y)-4; f=max(0,(base.ssr-sse)/2/(sse/df2)); rows.append({"Year":yr,"Method":"Chow joint level/slope","n before":n0,"n after":n1,"F":f,"p":stats.f.sf(f,2,df2),"Status":"Exploratory a priori date"})
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore"); za=zivot_andrews(y,regression="c",autolag="AIC")
        rows.append({"Year":int(years[int(za[4])]),"Method":"Zivot-Andrews intercept-break test","Statistic":za[0],"p":za[1],"Critical values":json.dumps({k:float(v) for k,v in za[2].items()}),"Status":"Small-sample test; null is a unit root with one intercept break"})
    except Exception as e: rows.append({"Method":"Zivot–Andrews","Status":"Unavailable: "+str(e)})
    out=pd.DataFrame(rows); out.to_csv(TAB/"structural_break_tests.csv",index=False); return out


def fit_one(name,y):
    y=np.asarray(y,float); s=pd.Series(y)
    if name=="Naive": return np.array([y[-1]])
    if name=="Historical mean": return np.array([y.mean()])
    if name=="Linear trend": return sm.OLS(y,sm.add_constant(np.arange(len(y)))).fit().predict([1,len(y)])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if name=="SES": f=SimpleExpSmoothing(s,initialization_method="estimated").fit(optimized=True)
        elif name=="Holt": f=Holt(s,initialization_method="estimated").fit(optimized=True)
        elif name=="AR(1)": f=AutoReg(s,lags=1,trend="c",old_names=False).fit()
        else:
            order={"MA(1)":(0,0,1),"ARMA(1,1)":(1,0,1),"ARIMA(0,1,0)":(0,1,0),"ARIMA(1,1,0)":(1,1,0),"ARIMA(0,1,1)":(0,1,1)}[name]
            f=ARIMA(s,order=order,trend="t" if order[1] else "c").fit()
    return np.asarray(f.forecast(1),float)


def compare_models(y):
    names=["Naive","Historical mean","Linear trend","SES","Holt","AR(1)","MA(1)","ARMA(1,1)","ARIMA(0,1,0)","ARIMA(1,1,0)","ARIMA(0,1,1)"]
    first=20; actual=np.asarray(y[first:],float); predictions={}; errors={n:[] for n in names}; scales=[]
    for origin in range(first,len(y)):
        train=np.asarray(y[:origin],float); scales.append(np.mean(np.abs(np.diff(train))))
        for name in names:
            try: errors[name].append(float(fit_one(name,train)[0]))
            except Exception: errors[name].append(np.nan)
    rows=[]
    for name,preds in errors.items():
        p=np.asarray(preds); valid=np.isfinite(p); e=actual[valid]-p[valid]; scale=np.asarray(scales)[valid]
        if not valid.any(): continue
        rows.append({"Model":name,"Origins":int(valid.sum()),"RMSE":np.sqrt(np.mean(e**2)),"MAE":np.mean(np.abs(e)),"MAPE (%)":np.mean(np.abs(e/actual[valid]))*100,"MASE":np.mean(np.abs(e)/scale)})
        predictions[name]=p
    table=pd.DataFrame(rows).sort_values(["MASE","RMSE"]); table.to_csv(TAB/"expanding_window_model_comparison.csv",index=False)
    table=table.merge(information_criteria(y),on="Model",how="left")
    table.to_csv(TAB/"expanding_window_model_comparison.csv",index=False)
    pd.DataFrame({"Year":np.arange(2011,2026),"Actual":actual,**predictions}).to_csv(TAB/"expanding_window_predictions.csv",index=False)
    return table,predictions,actual


def information_criteria(y):
    """Full-sample AIC/BIC are supplementary and not used to select the winner."""
    y=np.asarray(y,float); s=pd.Series(y); specs={"Historical mean":("ols",None),"Linear trend":("trend",None),"SES":("ses",None),"Holt":("holt",None),"AR(1)":("ar",None),"MA(1)":("arima",(0,0,1)),"ARMA(1,1)":("arima",(1,0,1)),"ARIMA(0,1,0)":("arima",(0,1,0)),"ARIMA(1,1,0)":("arima",(1,1,0)),"ARIMA(0,1,1)":("arima",(0,1,1))}
    rows=[]
    for name,(kind,order) in specs.items():
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                if kind=="ols": fit=sm.OLS(y,np.ones((len(y),1))).fit()
                elif kind=="trend": fit=sm.OLS(y,sm.add_constant(np.arange(len(y)))).fit()
                elif kind=="ses": fit=SimpleExpSmoothing(s,initialization_method="estimated").fit(optimized=True)
                elif kind=="holt": fit=Holt(s,initialization_method="estimated").fit(optimized=True)
                elif kind=="ar": fit=AutoReg(s,lags=1,trend="c",old_names=False).fit()
                else: fit=ARIMA(s,order=order,trend="t" if order[1] else "c").fit()
            rows.append({"Model":name,"Full-sample AIC":float(fit.aic),"Full-sample BIC":float(fit.bic)})
        except Exception: rows.append({"Model":name,"Full-sample AIC":np.nan,"Full-sample BIC":np.nan})
    rows.append({"Model":"Naive","Full-sample AIC":np.nan,"Full-sample BIC":np.nan})
    out=pd.DataFrame(rows); out.to_csv(TAB/"full_sample_aic_bic.csv",index=False); return out


def fit_final(name,y):
    s=pd.Series(np.asarray(y,float))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if name=="Naive": return lambda h: np.repeat(float(s.iloc[-1]),h),np.diff(s)
        if name=="Historical mean": return lambda h: np.repeat(float(s.mean()),h),s-s.mean()
        if name=="Linear trend":
            f=sm.OLS(s,sm.add_constant(np.arange(len(s)))).fit()
            return lambda h:f.predict(sm.add_constant(np.arange(len(s),len(s)+h),has_constant="add")),f.resid
        if name=="SES": f=SimpleExpSmoothing(s,initialization_method="estimated").fit(optimized=True)
        elif name=="Holt": f=Holt(s,initialization_method="estimated").fit(optimized=True)
        elif name=="AR(1)": f=AutoReg(s,lags=1,trend="c",old_names=False).fit()
        else:
            order={"MA(1)":(0,0,1),"ARMA(1,1)":(1,0,1),"ARIMA(0,1,0)":(0,1,0),"ARIMA(1,1,0)":(1,1,0),"ARIMA(0,1,1)":(0,1,1)}[name]
            f=ARIMA(s,order=order,trend="t" if order[1] else "c").fit()
    return lambda h:np.asarray(f.forecast(h),float),np.asarray(f.resid,float)


def forecast_and_diagnostics(name,y):
    fn,resid=fit_final(name,y); point=np.asarray(fn(5),float); resid=np.asarray(resid,float); resid=resid[np.isfinite(resid)]; centered=resid-resid.mean()
    rng=np.random.default_rng(20261112); n_sims=20000
    innovations=rng.choice(centered,size=(n_sims,5),replace=True)
    # Integrated ARIMA paths accumulate innovations; stationary/error-correction
    # candidates use horizon-wise errors around their point forecasts.
    if name.startswith("ARIMA(") and name.split(",")[1].strip()=="1":
        shocks=np.cumsum(innovations,axis=1)
    else:
        shocks=innovations
    sims=point[None,:]+shocks
    f=pd.DataFrame({"Year":range(2026,2031),"Point forecast":point,"Lower 80%":np.quantile(sims,.10,axis=0),"Upper 80%":np.quantile(sims,.90,axis=0),"Lower 95%":np.quantile(sims,.025,axis=0),"Upper 95%":np.quantile(sims,.975,axis=0)})
    f.to_csv(TAB/"unemployment_forecast_2026_2030.csv",index=False)
    lag=min(10,max(1,len(resid)//5)); lb=acorr_ljungbox(resid,lags=[lag],return_df=True); jb=jarque_bera(resid); arch=het_arch(resid,nlags=min(4,max(1,len(resid)//5)))
    diag={"Model":name,"Ljung-Box lag":lag,"Ljung-Box Q":float(lb.lb_stat.iloc[0]),"Ljung-Box p":float(lb.lb_pvalue.iloc[0]),"Jarque-Bera":float(jb[0]),"Jarque-Bera p":float(jb[1]),"ARCH LM":float(arch[0]),"ARCH LM p":float(arch[1])}
    (TAB/"final_model_diagnostics.json").write_text(json.dumps(diag,indent=2),encoding="utf-8")
    return f,sims,resid,diag


def regression_analysis(d):
    X=sm.add_constant(d[XCOLS]); y=d[YCOL]; fit=sm.OLS(y,X).fit(cov_type="HC3")
    coef=pd.DataFrame({"Coefficient":fit.params,"HC3 SE":fit.bse,"t":fit.tvalues,"p":fit.pvalues,"CI lower":fit.conf_int()[0],"CI upper":fit.conf_int()[1]})
    vif=pd.DataFrame({"Variable":X.columns,"VIF":[variance_inflation_factor(X.values,i) for i in range(X.shape[1])]})
    coef.to_csv(TAB/"synthetic_regression_hc3.csv"); vif.to_csv(TAB/"vif.csv",index=False)
    stress=(d.Period_Type=="Stress period").astype(int); group=sm.OLS(y,sm.add_constant(stress)).fit(cov_type="HC3")
    d.groupby("Period_Type")[YCOL].agg(["count","mean","std","min","max"]).to_csv(TAB/"period_type_descriptives.csv")
    return fit,coef,vif,group


def figures(d,metrics,predictions,actual,forecast,resid,regfit):
    paths={}; years=np.arange(2011,2026)
    fig,ax=plt.subplots(figsize=(9,4.8)); ax.plot(years,actual,color="black",lw=2,marker="o",ms=3,label="Actual")
    for m in metrics.sort_values("MASE").head(5).Model: ax.plot(years,predictions[m],lw=1.2,marker=".",label=m)
    ax.set_title("Unemployment Rate: Expanding-Window Actual and Predicted Values"); ax.set_xlabel("Year"); ax.set_ylabel("Unemployment Rate (%)"); ax.legend(fontsize=8,ncol=2,frameon=False); axis_style(ax); paths["actual_predicted"]=save(fig,"actual_vs_predicted.png")
    fig,ax=plt.subplots(figsize=(9,5)); ax.barh(metrics.Model,metrics.MASE,color=BLUE); ax.invert_yaxis(); ax.set_title("Unemployment Forecast Model Comparison"); ax.set_xlabel("Mean absolute scaled error (lower is better)"); ax.set_ylabel("Candidate model"); axis_style(ax); ax.set_yticks(np.arange(len(metrics)),labels=metrics.Model); paths["model_comparison"]=save(fig,"model_comparison.png")
    fig,ax=plt.subplots(figsize=(9,4.8)); ax.plot(d.Year,d[YCOL],color=BLUE,lw=2,marker="o",ms=3.5,label="Observed (1991–2025)"); ax.plot(forecast.Year,forecast["Point forecast"],color=RED,lw=2,ls="--",marker="o",label="Forecast")
    ax.fill_between(forecast.Year,forecast["Lower 95%"],forecast["Upper 95%"],color=RED,alpha=.13,label="95% residual-bootstrap interval"); ax.fill_between(forecast.Year,forecast["Lower 80%"],forecast["Upper 80%"],color=ORANGE,alpha=.22,label="80% residual-bootstrap interval"); ax.axvline(2025.5,color="#555",ls=":",label="Forecast starts")
    ax.set_title("Unemployment Rate: 2026–2030 Conditional Forecast"); ax.set_xlabel("Year"); ax.set_ylabel("Unemployment Rate (%)"); ax.legend(fontsize=8,frameon=False); axis_style(ax); paths["forecast"]=save(fig,"forecast_2026_2030.png")
    fig,axs=plt.subplots(2,2,figsize=(9,6.6)); axs[0,0].plot(np.arange(len(resid)),resid,color=PURPLE); axs[0,0].axhline(0,color="#555",lw=.8); axs[0,0].set_title("Residuals over observations"); axs[0,0].set_xlabel("Observation number"); axs[0,0].set_ylabel("Residual (percentage points)")
    axs[0,1].hist(resid,bins="auto",color=TEAL,edgecolor="white"); axs[0,1].set_title("Residual distribution"); axs[0,1].set_xlabel("Residual (percentage points)"); axs[0,1].set_ylabel("Frequency (observations)")
    r_acf=acf(resid,nlags=min(10,len(resid)//2-1),fft=False); axs[1,0].stem(np.arange(len(r_acf)),r_acf,linefmt=BLUE,markerfmt="o",basefmt="#555"); axs[1,0].set_title("Residual ACF"); axs[1,0].set_xlabel("Lag (years)"); axs[1,0].set_ylabel("Autocorrelation")
    sm.qqplot(resid,line="s",ax=axs[1,1],markerfacecolor=BLUE,markeredgecolor=BLUE,alpha=.75); axs[1,1].set_title("Residual normal Q–Q plot"); axs[1,1].set_xlabel("Theoretical normal quantiles"); axs[1,1].set_ylabel("Observed residual quantiles")
    for a in axs.flat: axis_style(a)
    paths["residual_diagnostics"]=save(fig,"final_model_residual_diagnostics.png")
    fig,axs=plt.subplots(1,2,figsize=(9,4.2)); fitted=np.asarray(regfit.fittedvalues); rr=np.asarray(regfit.resid); axs[0].scatter(fitted,rr,color=BLUE,s=24); axs[0].axhline(0,color=RED,ls="--"); axs[0].set_title("Synthetic regression: residuals vs fitted"); axs[0].set_xlabel("Fitted unemployment rate (%)"); axs[0].set_ylabel("Residual (percentage points)"); sm.qqplot(rr,line="s",ax=axs[1],markerfacecolor=TEAL,markeredgecolor=TEAL); axs[1].set_title("Regression residual Q–Q plot"); axs[1].set_xlabel("Theoretical normal quantiles"); axs[1].set_ylabel("Observed residual quantiles")
    for a in axs: axis_style(a)
    paths["regression_diagnostics"]=save(fig,"synthetic_regression_diagnostics.png")
    return paths


def add_table(doc,df,title):
    doc.add_heading(title,level=2); t=doc.add_table(rows=1,cols=len(df.columns)); t.style="Light Shading Accent 1"
    for c,n in zip(t.rows[0].cells,df.columns): c.text=str(n)
    for row in df.itertuples(index=False,name=None):
        cells=t.add_row().cells
        for cell,v in zip(cells,row): cell.text="" if pd.isna(v) else (f"{v:.4f}" if isinstance(v,(float,np.floating)) else str(v))


def report(d,valid,desc,st,br,metrics,forecast,diag,reg,graphfiles,selected):
    doc=Document(); sec=doc.sections[0]; sec.top_margin=Inches(.65); sec.bottom_margin=Inches(.65); sec.left_margin=Inches(.7); sec.right_margin=Inches(.7); doc.styles["Normal"].font.name="Times New Roman"; doc.styles["Normal"].font.size=Pt(10)
    doc.add_heading("Annual Unemployment Series: Statistical Review and Forecasting Exercise",0)
    doc.add_paragraph("Illustrative analysis of the supplied 1991-2025 CSV. The unemployment series source is undocumented in the file. All four other economic-looking numeric series are synthetic demonstration data and cannot support empirical economic claims.")
    doc.add_paragraph(f"Unemployment ranges from {d[YCOL].min():.1f}% in {int(d.loc[d[YCOL].idxmin(),'Year'])} to {d[YCOL].max():.1f}% in {int(d.loc[d[YCOL].idxmax(),'Year'])}. It changes by {d.loc[d.Year==2019,YCOL].iloc[0]-d.loc[d.Year==2015,YCOL].iloc[0]:+.1f} percentage points between 2015 and 2019, then by {d.loc[d.Year==2025,YCOL].iloc[0]-d.loc[d.Year==2020,YCOL].iloc[0]:+.1f} points between 2020 and 2025. The whole-period linear slope is {sm.OLS(d[YCOL],sm.add_constant(d.Year-d.Year.min())).fit().params.iloc[1]:+.3f} percentage points per year; it does not capture all turning points.")
    headings=["1. Introduction","2. Background to the study","3. Description of the dataset","4. Research objectives","5. Methodology","6. Descriptive statistical analysis","7. Graphical and exploratory analysis","8. Stationarity analysis","9. Structural break analysis","10. Model identification","11. Model estimation","12. Forecast model comparison","13. Residual diagnostics","14. Multivariate analysis","15. Forecast results","16. Discussion of findings","17. Limitations of the study","18. Conclusion","19. Recommendations","20. References"]
    texts=["The study evaluates the supplied annual unemployment observations, stationarity and potential breaks, parsimonious forecasts, and illustrative relationships with synthetic regressors.","Annual unemployment may reflect persistent cyclical and structural dynamics. A 35-point sample limits power and makes validation design consequential.",f"The CSV contains {valid['n']} ordered, complete annual rows from {valid['start']}–{valid['end']}. Source and measurement definition for unemployment were not supplied. The other numeric columns are synthetic; Period_Type flags three demonstration stress years.","Describe the series, assess time-series properties, compare forecast candidates, and demonstrate why synthetic predictors cannot establish real economic relationships.","No observations are altered or excluded. Descriptives use sample variance/SD. ADF, PP, KPSS are run on levels and first differences under constant and constant+trend specifications. Candidate forecasts use expanding annual origins starting after 20 training points; MASE, RMSE, MAE and MAPE are reported. No seasonal model is fit to annual data.","Table 1 summarizes central tendency, spread, shape, annual change, growth and exploratory IQR flags. Outlier flags are not a basis for data manipulation.","Plots display every numeric series, its trailing three-year mean, distributions, box plots and Pearson correlations. Correlations involving generated predictors are artificial/illustrative.","Table 2 reports test statistics, p-values and critical values. ADF/PP null is a unit root; KPSS null is stationarity. Failure to reject is not proof. Conflicting results are treated as inconclusive.","Table 3 reports specified-date Chow checks and an endogenous one-break Zivot–Andrews test. Dates are exploratory a priori comparisons; repeated tests raise multiplicity concerns. Multiple-break estimation is not forced with only 35 observations.","ACF/PACF guide low-order nonseasonal candidates. No seasonal model is suitable for annual observations absent a within-year cycle.","Candidates are naïve, historical mean, linear trend, SES, Holt, AR(1), MA(1), ARMA(1,1), and low-order ARIMA. Fit failures are not replaced with fabricated results.",f"Table 4 ranks models by expanding-window MASE, with RMSE/MAE/MAPE. The winner under this exact design is {selected}; closeness in scores should temper claims. This directly rechecks the historical-mean versus Holt discrepancy over 15 rolling origins.","Table 5 reports Ljung–Box, Jarque–Bera and ARCH LM residual checks. Short-sample diagnostics have low power; nonnormality/heteroskedasticity weaken conventional intervals.","HC3 OLS uses four synthetic predictors; coefficient p-values and VIF are descriptive methods illustrations only, not empirical economics or causal effects. Period_Type's three marked observations make group comparison underpowered. ARDL, bounds tests, ECM and VAR are not justified by short sample, synthetic X variables, and unsettled integration evidence.","Table 6 gives conditional 2026–2030 forecasts and residual-bootstrap 80%/95% intervals. Bootstrap quantiles resample centered fitted errors and assume these errors are informative about the future; they do not account for future breaks or full parameter uncertainty.","The supplied observations rise from 4.5% in 2015 to a peak of 5.7% in 2019, then decline to 3.0% by 2025. The 2020 value is 5.4%; the largest one-year drop is from 2020 to 2021. These patterns alone do not prove structural breaks.","Limitations include undocumented unemployment provenance, synthetic predictors, n=35, low test power, date-selection multiplicity, only 15 evaluation origins, and bootstrap assumptions.",f"The selected model ({selected}) is preferred only under the defined expanding-window MASE ranking and remains conditional; it is not a proven data-generating process.","Document the unemployment source, definition, units and vintage before research submission. Replace synthetic regressors with sourced data or label the work a methods demonstration. Re-evaluate with more observations and external validation.","Dickey, D. A., & Fuller, W. A. (1979). Distribution of the estimators for autoregressive time series with a unit root. Journal of the American Statistical Association, 74(366), 427–431. Phillips, P. C. B., & Perron, P. (1988). Testing for a unit root in time series regression. Biometrika, 75(2), 335–346. Kwiatkowski, D., Phillips, P. C. B., Schmidt, P., & Shin, Y. (1992). Testing the null hypothesis of stationarity against the alternative of a unit root. Journal of Econometrics, 54, 159–178. Zivot, E., & Andrews, D. W. K. (1992). Further evidence on the Great Crash, the oil-price shock, and the unit-root hypothesis. Journal of Business & Economic Statistics, 10(3), 251–270."]
    for title,text in zip(headings,texts):
        doc.add_heading(title,level=1); doc.add_paragraph(text)
        if title.startswith("6."):
            add_table(doc,desc[["Variable","N","Mean","Median","Minimum","Maximum","Range"]],"Table 1. Descriptive statistics: central tendency and range")
            add_table(doc,desc[["Variable","Variance","Standard deviation","Skewness","Excess kurtosis"]],"Table 1 (continued). Distribution and dispersion")
            add_table(doc,desc[["Variable","Mean absolute annual change","Mean annual growth (%)","IQR outlier years"]],"Table 1 (continued). Annual change, growth, and exploratory outlier flags")
            row=desc[desc.Variable==YCOL].iloc[0]
            doc.add_paragraph(f"The supplied unemployment series has mean {row['Mean']:.2f}% and median {row['Median']:.2f}%, with standard deviation {row['Standard deviation']:.2f} percentage points and range {row['Range']:.1f} points. The upper tail reflects the 2015-2019 increase; the large declines in 2021-2022 contribute substantial negative annual changes. IQR flags are screening alerts only, not grounds for excluding values.")
        if title.startswith("7."):
            number=1
            for variable in NUMERIC:
                for suffix,description in (("_series","annual series, linear trend, and three-year moving average"),("_distribution","distribution and box plot")):
                    key=variable+suffix; doc.add_paragraph(f"Figure {number}. {variable.replace('_',' ')}: {description}.",style="Caption"); doc.add_picture(str(graphfiles[key]),width=Inches(6.1)); number+=1
            for key,caption in (("heatmap","Pearson correlation heatmap; explanatory series are synthetic"),("first_difference","Unemployment first differences"),("acf_pacf","Unemployment ACF and PACF")):
                doc.add_paragraph(f"Figure {number}. {caption}.",style="Caption"); doc.add_picture(str(graphfiles[key]),width=Inches(6.1)); number+=1
        if title.startswith("8."):
            compact=st[["Series","Deterministic","Test","Statistic","P-value","Null","Alternative","Critical 1%","Critical 5%","Critical 10%"]]
            add_table(doc,compact,"Table 2. Unemployment stationarity tests")
            doc.add_paragraph("At levels, constant-only ADF p=0.0881 rejects the unit-root null at 10% only; trend ADF p=0.105 does not reject at 1%, 5%, or 10%. PP p-values are 0.605 (constant) and 0.903 (constant plus trend), so neither rejects. KPSS fails to reject stationarity in both specifications (p-values are capped at 0.10), which is not proof of stationarity. In first differences, constant ADF p=0.0019 rejects at 1%, 5%, and 10%; constant PP p=0.0425 rejects at 5% and 10% but not 1%. With trend terms, ADF p=0.155 and PP p=0.153 do not reject at any level. KPSS fails to reject stationarity for both first-difference specifications. This is mixed evidence; I(1) is plausible under constant-only tests but not established across specifications, especially given a detected 2015 Chow change and low sample size.")
        if title.startswith("9."):
            add_table(doc,br,"Table 3. Structural break tests")
            chow=float(br[(br.Year==2015)&(br.Method=="Chow joint level/slope")]["p"].iloc[0]); za=br[br.Method.str.contains("Zivot",na=False)].iloc[0]
            doc.add_paragraph(f"The specified 2015 Chow test finds a joint level/slope change (p={chow:.4g}) under the piecewise linear specification. Because several dates were checked, treat this as exploratory. Zivot-Andrews chooses {int(za.Year)} as its one break but does not reject the unit-root null with a break (p={float(za.p):.3f}). These tests have different nulls and do not prove a break-free or stationary process. Chow tests for 2019-2021 were withheld because fewer than eight post-break observations remain.")
        if title.startswith("12."):
            add_table(doc,metrics,"Table 4. Expanding-window forecast performance")
            h=metrics[metrics.Model=="Holt"].iloc[0]; m=metrics[metrics.Model=="Historical mean"].iloc[0]; best=metrics.iloc[0]
            doc.add_paragraph(f"The earlier result that the historical mean beat Holt is not reproduced under this different validation design: over the same 15 expanding origins, Holt has MASE {h.MASE:.3f} versus {m.MASE:.3f} for the historical mean. This difference can arise because a single terminal holdout and multiple one-step rolling origins weight the 2020-2022 decline differently. {best.Model} ranks first (MASE {best.MASE:.3f}, RMSE {best.RMSE:.3f}, MAE {best.MAE:.3f}); the preference is conditional on the origins and model set, while AIC/BIC remain supplementary.")
            doc.add_paragraph("Full-sample AIC/BIC are supplementary in the accompanying full_sample_aic_bic.csv. They are computed on the complete series and are not used as out-of-sample forecast scores or to select the reported winner.")
            for key,cap in [("actual_predicted","Figure 14. Actual and expanding-window predicted values."),("model_comparison","Figure 15. Candidate model MASE comparison.")]: doc.add_paragraph(cap,style="Caption"); doc.add_picture(str(graphfiles[key]),width=Inches(6.1))
        if title.startswith("13."):
            add_table(doc,pd.DataFrame([diag]),"Table 5. Selected-model residual diagnostics")
            doc.add_paragraph(f"At 5%, Ljung-Box does not detect residual autocorrelation (p={diag['Ljung-Box p']:.3f}) and ARCH LM does not detect conditional heteroskedasticity (p={diag['ARCH LM p']:.3f}). Jarque-Bera strongly rejects normality (p={diag['Jarque-Bera p']:.3g}), consistent with the influential large residual visible in the plot. The model converges, but convergence is not evidence of adequacy. Residual-bootstrap intervals are used to avoid relying solely on Gaussian quantiles; they still cannot guarantee nominal coverage.")
            doc.add_paragraph("Figure 16. Final-model residual time series, distribution, ACF, and normal Q-Q plot.",style="Caption"); doc.add_picture(str(graphfiles["residual_diagnostics"]),width=Inches(6.1))
        if title.startswith("14."):
            fit,coef,vif,group=reg; add_table(doc,coef.reset_index(names="Term"),"Table 6. HC3 regression with synthetic predictors"); add_table(doc,vif,"Table 7. Variance inflation factors")
            j=jarque_bera(np.asarray(fit.resid)); bp=__import__("statsmodels.stats.diagnostic",fromlist=["het_breuschpagan"]).het_breuschpagan(fit.resid,fit.model.exog)
            doc.add_paragraph(f"The HC3 robust joint Wald/F test is {float(fit.fvalue):.3f} (p={float(fit.f_pvalue):.4g}); R-squared={fit.rsquared:.3f}. Regression residual Jarque-Bera p={float(j[1]):.3g}; Breusch-Pagan LM p={float(bp[1]):.3g}. These diagnostics describe a deliberately synthetic relationship and do not turn it into economic evidence. VIF values should be read with the small sample and construction of the predictors in mind.")
            doc.add_paragraph(f"Stress-period contrast: {group.params.iloc[1]:.3f} percentage points (HC3 p={group.pvalues.iloc[1]:.3f}); only three years were classified as stress.")
            period_table=d.groupby("Period_Type")[YCOL].agg(["count","mean","std","min","max"]).reset_index(); add_table(doc,period_table,"Table 8. Unemployment by illustrative period type")
            doc.add_paragraph("Figure 17. Residual-versus-fitted and residual Q-Q diagnostics for the synthetic-predictor regression.",style="Caption"); doc.add_picture(str(graphfiles["regression_diagnostics"]),width=Inches(6.1))
        if title.startswith("15."): add_table(doc,forecast,"Table 9. Conditional forecasts"); doc.add_paragraph("Figure 18. 2026-2030 unemployment forecasts and 80%/95% residual-bootstrap intervals.",style="Caption"); doc.add_picture(str(graphfiles["forecast"]),width=Inches(6.1))
    p=OUT/"comprehensive_time_series_report.docx"; doc.save(p); return p


def main():
    setup(); d,v=validate(); desc=descriptives(d); graphs=explore_graphs(d); st=stationarity(d[YCOL]); br=breaks(d)
    metrics,preds,actual=compare_models(d[YCOL].to_numpy());
    if metrics.empty: raise RuntimeError("No usable forecast candidate.")
    selected=str(metrics.iloc[0].Model); forecast,sims,resid,diag=forecast_and_diagnostics(selected,d[YCOL].to_numpy()); reg=regression_analysis(d)
    graphs.update(figures(d,metrics,preds,actual,forecast,resid,reg[0]))
    report_path=report(d,v,desc,st,br,metrics,forecast,diag,reg,graphs,selected)
    summary={"selected_model_by_expanding_MASE":selected,"validation_origins":int(metrics.iloc[0].Origins),"forecast":forecast.to_dict("records"),"diagnostics":diag,"report":str(report_path),"figure_count":len(graphs),"output_folder":str(OUT)}
    (OUT/"analysis_summary.json").write_text(json.dumps(summary,indent=2,default=float),encoding="utf-8"); print(json.dumps(summary,indent=2,default=float))

if __name__=="__main__": main()
