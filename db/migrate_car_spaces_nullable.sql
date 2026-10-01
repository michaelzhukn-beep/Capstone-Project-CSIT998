-- car_spaces: 缺失(未知)与 0 个车位要能区分。
-- 本文件只是迁移说明与语句,**测试从不执行它**;对已有数据库执行前需所有者确认。
--
-- 1) 放宽列约束(安全、可逆;不改任何现有值):
ALTER TABLE properties ALTER COLUMN car_spaces DROP NOT NULL;
ALTER TABLE properties ALTER COLUMN car_spaces DROP DEFAULT;
--
-- 2) 已有数据里的 0 无法在库内区分「未知」和「真的 0」,所以这里**不做任何数据改写去猜**。
--    要得到正确的 NULL,必须 reload:用修复后的 pipeline/load_properties.py 重新导入(缺失 Car -> NULL)。
--
-- 3) reload 之后必须重训并重建估值相关产物,否则 NULL 行与旧模型/旧交叉拟合键对不上:
--      python -m app.analytics.train_valuation     (car_spaces 现在会读到 NaN,XGBoost 原生支持缺失)
--      python -m app.analytics.crossfit_valuation / calibrate_valuation
--    (valuation._norm 把 None 与 NaN 都记成空串,库内 NULL 与推理输入 None 一致。)
-- 4) reload 会让房源 id 重新分配,收藏夹按旧 id 取详情可能指向另一套房(见 PROJECT_STATE 风险)。
