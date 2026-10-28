"""Aggregation optimization must preserve the original scalar acceptance rules."""
import unittest
import numpy as np
import pandas as pd
from goxtrade.strategies.signal_candles import signal_candles


def scalar(minutes, now, interval):
    frame=minutes.copy()
    frame['time']=pd.to_datetime(frame.time,utc=True)
    if 'complete' in frame: frame=frame.loc[frame.complete.eq(True)]
    if 'asof_time' in frame:
        observed=pd.to_datetime(frame.asof_time,utc=True,errors='coerce')
        frame=frame.loc[frame.asof_time.isna() | (observed.notna() & observed.le(pd.Timestamp(now)))]
    frame=frame.loc[frame.time+pd.Timedelta(minutes=1)<=pd.Timestamp(now)].sort_values('time').drop_duplicates('time',keep='last')
    rows=[]
    for stamp,group in frame.groupby(frame.time.dt.floor(f'{interval}min')):
        if len(group)!=interval or not group.time.reset_index(drop=True).equals(pd.Series(pd.date_range(stamp,periods=interval,freq='min'))):
            continue
        rows.append(dict(time=stamp,open=group.iloc[0].open,high=group.high.max(),low=group.low.min(),close=group.iloc[-1].close,volume=group.volume.sum(min_count=interval)))
    return pd.DataFrame(rows,columns=['time','open','high','low','close','volume'])


class CandleEquivalenceTests(unittest.TestCase):
    def test_scalar_equivalence_with_gaps_duplicates_and_availability(self):
        rng=np.random.default_rng(721)
        base=pd.DataFrame(dict(time=pd.date_range('2026-10-27T12:00Z',periods=241,freq='min'),
             open=rng.uniform(100,110,241),high=rng.uniform(111,120,241),low=rng.uniform(90,99,241),
             close=rng.uniform(100,110,241),volume=rng.integers(0,1000,241).astype(float)))
        variants=[base,base.drop(index=[2,33,70]),pd.concat([base,base.iloc[[22]]],ignore_index=True)]
        marked=base.copy();marked['complete']=True;marked.loc[[4,66,240],'complete']=False
        variants.append(marked)
        observed=base.copy();observed['asof_time']=None;observed.loc[4,'asof_time']='2026-10-27T17:00:00+00:00';observed.loc[6,'asof_time']='invalid'
        variants.append(observed)
        misaligned=base.copy();misaligned.loc[5,'time']+=pd.Timedelta(seconds=1)
        variants.extend([misaligned,pd.concat([base,misaligned.iloc[[5]]],ignore_index=True)])
        missing=base.copy();missing.loc[[0,5,80],['open','close','volume']]=np.nan
        variants.append(missing)
        now=pd.Timestamp('2026-10-27T16:00:10Z')
        for i,frame in enumerate(variants):
            for interval in (1,3,5,10,15,30,60):
                with self.subTest(frame=i,interval=interval):
                    pd.testing.assert_frame_equal(signal_candles(frame,now,interval),scalar(frame,now,interval))

    def test_empty_and_no_complete_bucket_keep_schema(self):
        frame=pd.DataFrame(dict(time=pd.to_datetime(['2026-10-27T12:00Z']),open=[1.],high=[2.],low=[1.],close=[2.],volume=[3.]))
        for sample in (frame,frame.iloc[:0]):
            pd.testing.assert_frame_equal(signal_candles(sample,pd.Timestamp('2026-10-27T12:01Z'),15),scalar(sample,pd.Timestamp('2026-10-27T12:01Z'),15))
