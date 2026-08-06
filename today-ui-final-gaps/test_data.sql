-- Test data for qingshu_auth_test - populated user state
-- User ID: 3dcb7034-2299-4e9a-abab-f3b64cfa3706

-- Change events
INSERT INTO change_events (id, symbol, event_type, title, fact_summary, occurred_at, detected_at, source_name, source_url, data_status, rule_version, dedupe_hash, payload_json, created_at, updated_at)
VALUES
  ('ce-1', '688981.SH', 'earnings', '中芯国际Q2营收超预期', '中芯国际第二季度营收同比增长15.2%，超出市场预期，毛利率提升至26.8%', '2026-08-04T01:00:00+00:00', '2026-08-04T06:00:00+00:00', '财务报告', '', 'verified', 'v1', 'hash-ce-1', '{}', '2026-08-04T06:00:00+00:00', '2026-08-04T06:00:00+00:00'),
  ('ce-2', '000063.SZ', 'news', '中兴通讯获AI服务器大单', '中兴通讯公告获得某大型互联网公司AI服务器订单，金额约50亿元', '2026-08-03T22:00:00+00:00', '2026-08-04T05:00:00+00:00', '公司公告', '', 'verified', 'v1', 'hash-ce-2', '{}', '2026-08-04T05:00:00+00:00', '2026-08-04T05:00:00+00:00'),
  ('ce-3', '688981.SH', 'rating', '多家机构上调中芯国际评级', '中信证券、国泰君安等5家券商上调中芯国际评级至买入，目标价上调至75元', '2026-08-04T02:00:00+00:00', '2026-08-04T07:00:00+00:00', '研报汇总', '', 'verified', 'v1', 'hash-ce-3', '{}', '2026-08-04T07:00:00+00:00', '2026-08-04T07:00:00+00:00')
ON CONFLICT (id) DO NOTHING;

-- User change links
INSERT INTO user_change_links (id, user_id, change_event_id, symbol, relevance_status, created_at, updated_at)
VALUES
  ('ucl-1', '3dcb7034-2299-4e9a-abab-f3b64cfa3706', 'ce-1', '688981.SH', 'relevant', '2026-08-04T06:00:00+00:00', '2026-08-04T06:00:00+00:00'),
  ('ucl-2', '3dcb7034-2299-4e9a-abab-f3b64cfa3706', 'ce-2', '000063.SZ', 'relevant', '2026-08-04T05:00:00+00:00', '2026-08-04T05:00:00+00:00'),
  ('ucl-3', '3dcb7034-2299-4e9a-abab-f3b64cfa3706', 'ce-3', '688981.SH', 'relevant', '2026-08-04T07:00:00+00:00', '2026-08-04T07:00:00+00:00')
ON CONFLICT (id) DO NOTHING;
