import aws_cdk as cdk
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct

NS = "Insightly"


def m(name: str, stat: str, status: str = "ok", period: int = 5) -> cw.Metric:
    return cw.Metric(
        namespace=NS,
        metric_name=name,
        statistic=stat,
        dimensions_map={"Service": "insightly", "Status": status},
        period=cdk.Duration.minutes(period),
    )


class OpsStack(cdk.Stack):
    def __init__(self, scope: Construct, id: str, *, service, **kw) -> None:
        super().__init__(scope, id, **kw)
        email = self.node.try_get_context("alertEmail")
        budget_usd = float(self.node.try_get_context("monthlyBudgetUsd") or 50)
        topic = sns.Topic(self, "Alerts", display_name="Insightly alerts")
        if email:
            topic.add_subscription(subs.EmailSubscription(email))

        alb = service.service.load_balancer
        dash = cw.Dashboard(self, "Dashboard", dashboard_name="Insightly")
        dash.add_widgets(
            cw.TextWidget(markdown="# Insightly: quality, latency, cost", width=24, height=1),
            cw.GraphWidget(
                title="Questions by outcome",
                width=8,
                left=[
                    m("LatencyMs", "SampleCount", s).with_(label=s)
                    for s in ("ok", "clarify", "refused", "failed", "budget_exceeded")
                ],
            ),
            cw.GraphWidget(
                title="Latency ms (p50 / p95)", width=8, left=[m("LatencyMs", "p50"), m("LatencyMs", "p95")]
            ),
            cw.GraphWidget(
                title="LLM + Athena cost USD (sum per 5 min)", width=8, left=[m("CostUSD", "Sum")]
            ),
            cw.GraphWidget(
                title="SQL attempts per question (avg)", width=8, left=[m("SqlAttempts", "Average")]
            ),
            cw.GraphWidget(title="Tokens", width=8, left=[m("InputTokens", "Sum"), m("OutputTokens", "Sum")]),
            cw.GraphWidget(title="ALB 5xx", width=8, left=[alb.metrics.http_code_target(cw_actions_code())]),
        )
        alarms = [
            cw.Alarm(
                self,
                "LatencyP95",
                metric=m("LatencyMs", "p95"),
                threshold=12000,
                evaluation_periods=3,
                alarm_description="p95 latency above SLO (12 s)",
            ),
            cw.Alarm(
                self,
                "FailedAnswers",
                metric=m("LatencyMs", "SampleCount", "failed"),
                threshold=10,
                evaluation_periods=1,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
                alarm_description="More than 10 failed questions in 5 minutes",
            ),
            cw.Alarm(
                self,
                "CostSpike",
                metric=m("CostUSD", "Sum", period=60),
                threshold=2.0,
                evaluation_periods=1,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
                alarm_description="More than $2 of model spend in one hour",
            ),
        ]
        for a in alarms:
            a.add_alarm_action(cw_actions.SnsAction(topic))

        if email:
            budgets.CfnBudget(
                self,
                "MonthlyBudget",
                budget=budgets.CfnBudget.BudgetDataProperty(
                    budget_name="insightly-monthly",
                    budget_type="COST",
                    time_unit="MONTHLY",
                    budget_limit=budgets.CfnBudget.SpendProperty(amount=budget_usd, unit="USD"),
                    cost_filters={"TagKeyValue": ["user:project$insightly"]},
                ),
                notifications_with_subscribers=[
                    budgets.CfnBudget.NotificationWithSubscribersProperty(
                        notification=budgets.CfnBudget.NotificationProperty(
                            comparison_operator="GREATER_THAN",
                            notification_type=kind,
                            threshold=pct,
                            threshold_type="PERCENTAGE",
                        ),
                        subscribers=[
                            budgets.CfnBudget.SubscriberProperty(address=email, subscription_type="EMAIL")
                        ],
                    )
                    for kind, pct in (("ACTUAL", 80), ("FORECASTED", 100))
                ],
            )


def cw_actions_code():
    from aws_cdk import aws_elasticloadbalancingv2 as elbv2

    return elbv2.HttpCodeTarget.TARGET_5XX_COUNT
