# apps/api/services/agents/analytics_agent.py
"""
Analytics Agent - Provides usage insights and predictions
Business analyst that watches system usage and provides insights to make it better
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
from crewai.tools import tool
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from apps.api.services.agents.base_agent import AgentContext, BaseAgent

logger = logging.getLogger(__name__)


class AnalyticsAgent(BaseAgent):
    """
    Analytics Agent - System usage analyst and insight generator

    Responsibilities:
    - Usage tracking and pattern analysis
    - Knowledge gap identification
    - Performance monitoring and optimization
    - Predictive analytics for content needs
    - Proactive insight generation
    """

    def __init__(self):
        super().__init__(
            name="analytics_agent",
            role="Business Intelligence Analyst",
            goal="Monitor system usage, identify patterns, and provide actionable insights for improvement",
            backstory="""I am an expert in data analysis and business intelligence with years of experience
            in identifying usage patterns, predicting user needs, and providing actionable insights.
            I excel at turning raw data into meaningful recommendations that improve system effectiveness.""",
        )

    def _initialize(self):
        """Initialize analytics components"""
        # Analytics data storage
        self.usage_data = defaultdict(list)
        self.query_patterns = defaultdict(int)
        self.document_access = defaultdict(int)
        self.performance_metrics = defaultdict(list)
        self.user_sessions = {}

        # Analysis configuration
        self.analysis_config = {
            "min_pattern_frequency": 3,
            "knowledge_gap_threshold": 0.7,
            "performance_alert_threshold": 2000,  # ms
            "insight_generation_interval": 3600,  # 1 hour
            "prediction_window_days": 7,
        }

        # Clustering for pattern detection
        self.pattern_clusterer = KMeans(n_clusters=5, random_state=42)
        self.scaler = StandardScaler()

        # Register tools
        self._register_tools()

    def _register_tools(self):
        """Register Analytics Agent specific tools"""

        @tool("Track Usage")
        def track_usage(event_type: str, event_data: Dict) -> str:
            """Track system usage events"""
            return self._track_usage_event(event_type, event_data)

        @tool("Analyze Patterns")
        def analyze_patterns(time_range: str = "24h") -> str:
            """Analyze usage patterns over specified time range"""
            return self._analyze_usage_patterns(time_range)

        @tool("Identify Knowledge Gaps")
        def identify_gaps() -> str:
            """Identify gaps in document coverage based on queries"""
            return self._identify_knowledge_gaps()

        @tool("Generate Insights")
        def generate_insights(focus_area: str = "general") -> str:
            """Generate actionable insights for system improvement"""
            return self._generate_actionable_insights(focus_area)

        self.register_tool(track_usage)
        self.register_tool(analyze_patterns)
        self.register_tool(identify_gaps)
        self.register_tool(generate_insights)

    async def process(
        self, input_data: Dict[str, Any], context: AgentContext
    ) -> Dict[str, Any]:
        """
        Process analytics request or event

        Input:
            - action: Type of analytics action (track, analyze, predict, report)
            - event_data: Event data for tracking
            - analysis_type: Type of analysis to perform
            - time_range: Time range for analysis

        Output:
            - insights: Generated insights
            - patterns: Identified patterns
            - gaps: Knowledge gaps
            - predictions: Future predictions
            - recommendations: Actionable recommendations
        """
        try:
            action = input_data.get("action", "analyze")

            if action == "track":
                # Track usage event
                event_result = await self.measure_operation(
                    lambda: self._process_usage_event(
                        input_data.get("event_data", {}), context
                    )
                )
                return event_result

            elif action == "analyze":
                # Perform comprehensive analysis
                time_range = input_data.get("time_range", "24h")

                # Analyze usage patterns
                patterns = await self.measure_operation(
                    lambda: self._perform_pattern_analysis(time_range)
                )

                # Identify knowledge gaps
                gaps = await self.measure_operation(
                    lambda: self._perform_gap_analysis()
                )

                # Analyze performance
                performance = await self.measure_operation(
                    lambda: self._analyze_system_performance(time_range)
                )

                # Generate predictions
                predictions = await self.measure_operation(
                    lambda: self._generate_predictions()
                )

                # Create insights
                insights = await self.measure_operation(
                    lambda: self._create_comprehensive_insights(
                        patterns, gaps, performance, predictions
                    )
                )

                return {
                    "insights": insights,
                    "patterns": patterns,
                    "knowledge_gaps": gaps,
                    "performance": performance,
                    "predictions": predictions,
                    "recommendations": self._generate_recommendations(insights),
                    "analytics_metrics": {
                        "patterns_found": len(patterns.get("clusters", [])),
                        "gaps_identified": len(gaps.get("gaps", [])),
                        "predictions_made": len(predictions.get("predictions", [])),
                        "processing_time_ms": self.metrics.average_latency,
                    },
                }

            elif action == "predict":
                # Generate predictions
                predictions = await self.measure_operation(
                    lambda: self._generate_targeted_predictions(
                        input_data.get("target", "content")
                    )
                )
                return predictions

            elif action == "report":
                # Generate detailed report
                report = await self.measure_operation(
                    lambda: self._generate_analytics_report(
                        input_data.get("report_type", "summary")
                    )
                )
                return report

            else:
                raise ValueError(f"Unknown analytics action: {action}")

        except Exception as e:
            logger.error(f"Analytics processing failed: {e}")
            self.metrics.record_error()
            raise

    async def _process_usage_event(
        self, event_data: Dict[str, Any], context: AgentContext
    ) -> Dict[str, Any]:
        """Process and store usage event"""

        event = {
            "timestamp": datetime.now().isoformat(),
            "session_id": context.session_id,
            "user_id": context.user_id,
            "conversation_id": context.conversation_id,
            **event_data,
        }

        # Store event by type
        event_type = event_data.get("type", "unknown")
        self.usage_data[event_type].append(event)

        # Update specific trackers
        if event_type == "query":
            self._update_query_patterns(event_data.get("query", ""))
        elif event_type == "document_access":
            self._update_document_access(event_data.get("document_id", ""))
        elif event_type == "performance":
            self._update_performance_metrics(event_data)

        # Check for real-time alerts
        alerts = self._check_real_time_alerts(event)

        return {
            "event_tracked": True,
            "event_id": f"{event_type}_{datetime.now().timestamp()}",
            "alerts": alerts,
        }

    async def _perform_pattern_analysis(self, time_range: str) -> Dict[str, Any]:
        """Analyze usage patterns using clustering and statistical analysis"""

        # Get events within time range
        events = self._filter_events_by_time(time_range)

        if len(events) < 10:
            return {
                "status": "insufficient_data",
                "message": "Not enough data for pattern analysis",
            }

        # Extract features for clustering
        features = self._extract_event_features(events)

        if len(features) > 0:
            # Normalize features
            normalized_features = self.scaler.fit_transform(features)

            # Perform clustering
            clusters = self.pattern_clusterer.fit_predict(normalized_features)

            # Analyze clusters
            cluster_analysis = self._analyze_clusters(events, clusters)

            # Identify temporal patterns
            temporal_patterns = self._identify_temporal_patterns(events)

            # Identify query patterns
            query_patterns = self._analyze_query_patterns()

            return {
                "clusters": cluster_analysis,
                "temporal_patterns": temporal_patterns,
                "query_patterns": query_patterns,
                "total_events": len(events),
                "time_range": time_range,
            }
        else:
            return {"status": "no_patterns", "message": "No clear patterns identified"}

    async def _perform_gap_analysis(self) -> Dict[str, Any]:
        """Identify knowledge gaps based on failed queries and search patterns"""

        gaps = []

        # Analyze failed queries
        failed_queries = [
            event
            for event in self.usage_data.get("query", [])
            if event.get("results_found", 1) == 0
        ]

        # Group failed queries by topic
        topic_failures = defaultdict(list)
        for query_event in failed_queries:
            topic = self._extract_query_topic(query_event.get("query", ""))
            topic_failures[topic].append(query_event)

        # Identify significant gaps
        for topic, failures in topic_failures.items():
            if len(failures) >= self.analysis_config["min_pattern_frequency"]:
                gaps.append(
                    {
                        "topic": topic,
                        "frequency": len(failures),
                        "example_queries": [f["query"] for f in failures[:3]],
                        "severity": self._calculate_gap_severity(failures),
                        "recommendation": self._generate_gap_recommendation(
                            topic, failures
                        ),
                    }
                )

        # Analyze document coverage
        coverage_gaps = self._analyze_document_coverage()

        # Analyze temporal gaps
        temporal_gaps = self._analyze_temporal_gaps()

        return {
            "gaps": sorted(gaps, key=lambda x: x["severity"], reverse=True),
            "coverage_gaps": coverage_gaps,
            "temporal_gaps": temporal_gaps,
            "total_failed_queries": len(failed_queries),
            "gap_summary": self._summarize_gaps(gaps),
        }

    async def _analyze_system_performance(self, time_range: str) -> Dict[str, Any]:
        """Analyze system performance metrics"""

        # Get performance events
        perf_events = self._filter_events_by_time(time_range, event_type="performance")

        if not perf_events:
            return {"status": "no_performance_data"}

        # Calculate statistics
        latencies = [e.get("latency_ms", 0) for e in perf_events]

        performance_stats = {
            "average_latency_ms": np.mean(latencies),
            "median_latency_ms": np.median(latencies),
            "p95_latency_ms": np.percentile(latencies, 95),
            "p99_latency_ms": np.percentile(latencies, 99),
            "max_latency_ms": np.max(latencies),
            "total_requests": len(perf_events),
        }

        # Identify performance issues
        issues = []
        if (
            performance_stats["p95_latency_ms"]
            > self.analysis_config["performance_alert_threshold"]
        ):
            issues.append(
                {
                    "type": "high_latency",
                    "severity": "high",
                    "description": f"95th percentile latency ({performance_stats['p95_latency_ms']:.0f}ms) exceeds threshold",
                }
            )

        # Analyze performance by operation type
        operation_performance = self._analyze_operation_performance(perf_events)

        # Identify performance trends
        trends = self._identify_performance_trends(perf_events)

        return {
            "statistics": performance_stats,
            "issues": issues,
            "operation_breakdown": operation_performance,
            "trends": trends,
            "time_range": time_range,
        }

    async def _generate_predictions(self) -> Dict[str, Any]:
        """Generate predictions based on historical patterns"""

        predictions = []

        # Predict query volume
        query_volume_prediction = self._predict_query_volume()
        predictions.append(
            {
                "type": "query_volume",
                "prediction": query_volume_prediction,
                "confidence": 0.75,
            }
        )

        # Predict popular topics
        topic_predictions = self._predict_popular_topics()
        predictions.append(
            {
                "type": "popular_topics",
                "prediction": topic_predictions,
                "confidence": 0.8,
            }
        )

        # Predict resource needs
        resource_predictions = self._predict_resource_needs()
        predictions.append(
            {
                "type": "resource_needs",
                "prediction": resource_predictions,
                "confidence": 0.7,
            }
        )

        # Predict knowledge gaps
        gap_predictions = self._predict_future_gaps()
        predictions.append(
            {"type": "future_gaps", "prediction": gap_predictions, "confidence": 0.65}
        )

        return {
            "predictions": predictions,
            "prediction_window": f"{self.analysis_config['prediction_window_days']} days",
            "generated_at": datetime.now().isoformat(),
        }

    async def _create_comprehensive_insights(
        self,
        patterns: Dict[str, Any],
        gaps: Dict[str, Any],
        performance: Dict[str, Any],
        predictions: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Create actionable insights from analysis results"""

        insights = []

        # Pattern-based insights
        if patterns.get("query_patterns"):
            top_patterns = patterns["query_patterns"][:3]
            insights.append(
                {
                    "category": "usage_patterns",
                    "title": "Most Common Query Types",
                    "description": f"Users frequently search for: {', '.join([p['pattern'] for p in top_patterns])}",
                    "impact": "high",
                    "recommendation": "Optimize content and search for these common query types",
                }
            )

        # Gap-based insights
        if gaps.get("gaps"):
            top_gap = gaps["gaps"][0] if gaps["gaps"] else None
            if top_gap:
                insights.append(
                    {
                        "category": "knowledge_gaps",
                        "title": f"Critical Knowledge Gap: {top_gap['topic']}",
                        "description": f"Failed queries about {top_gap['topic']} occurred {top_gap['frequency']} times",
                        "impact": "critical",
                        "recommendation": top_gap["recommendation"],
                    }
                )

        # Performance insights
        if performance.get("issues"):
            for issue in performance["issues"]:
                insights.append(
                    {
                        "category": "performance",
                        "title": "Performance Issue Detected",
                        "description": issue["description"],
                        "impact": issue["severity"],
                        "recommendation": "Investigate and optimize slow operations",
                    }
                )

        # Predictive insights
        if predictions.get("predictions"):
            volume_pred = next(
                (p for p in predictions["predictions"] if p["type"] == "query_volume"),
                None,
            )
            if volume_pred and volume_pred["prediction"].get("trend") == "increasing":
                insights.append(
                    {
                        "category": "predictive",
                        "title": "Expected Increase in Query Volume",
                        "description": "Query volume is predicted to increase by {:.0%} in the next week".format(
                            volume_pred["prediction"].get("change_rate", 0)
                        ),
                        "impact": "medium",
                        "recommendation": "Prepare for increased load by optimizing performance",
                    }
                )

        # Sort by impact
        impact_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        insights.sort(key=lambda x: impact_order.get(x["impact"], 4))

        return insights

    def _generate_recommendations(
        self, insights: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Generate specific recommendations based on insights"""

        recommendations = []

        for insight in insights:
            if insight["category"] == "knowledge_gaps":
                recommendations.append(
                    {
                        "priority": "high",
                        "action": "content_creation",
                        "description": f"Create or enhance documentation for: {insight['title']}",
                        "expected_impact": "Reduce failed queries by 30-50%",
                    }
                )

            elif insight["category"] == "performance":
                recommendations.append(
                    {
                        "priority": "critical",
                        "action": "performance_optimization",
                        "description": "Optimize slow operations identified in performance analysis",
                        "expected_impact": "Improve response time by 40%",
                    }
                )

            elif insight["category"] == "usage_patterns":
                recommendations.append(
                    {
                        "priority": "medium",
                        "action": "search_optimization",
                        "description": "Create specialized search indexes for common query patterns",
                        "expected_impact": "Improve search relevance by 25%",
                    }
                )

        return recommendations

    # Helper methods
    def _update_query_patterns(self, query: str):
        """Update query pattern tracking"""
        # Extract key terms
        terms = query.lower().split()

        # Update term frequency
        for term in terms:
            if len(term) > 2:  # Skip short words
                self.query_patterns[term] += 1

        # Update bigrams
        for i in range(len(terms) - 1):
            bigram = f"{terms[i]} {terms[i + 1]}"
            self.query_patterns[bigram] += 1

    def _update_document_access(self, document_id: str):
        """Update document access tracking"""
        self.document_access[document_id] += 1

    def _update_performance_metrics(self, event_data: Dict[str, Any]):
        """Update performance metrics"""
        metric_type = event_data.get("metric_type", "general")
        value = event_data.get("value", 0)

        self.performance_metrics[metric_type].append(
            {"timestamp": datetime.now(), "value": value}
        )

    def _filter_events_by_time(
        self, time_range: str, event_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Filter events by time range"""
        # Parse time range
        hours = 24
        if time_range.endswith("h"):
            hours = int(time_range[:-1])
        elif time_range.endswith("d"):
            hours = int(time_range[:-1]) * 24

        cutoff_time = datetime.now() - timedelta(hours=hours)

        # Filter events
        filtered = []

        event_types = [event_type] if event_type else self.usage_data.keys()

        for etype in event_types:
            for event in self.usage_data.get(etype, []):
                event_time = datetime.fromisoformat(event["timestamp"])
                if event_time > cutoff_time:
                    filtered.append(event)

        return filtered

    def _extract_event_features(self, events: List[Dict[str, Any]]) -> np.ndarray:
        """Extract numerical features from events for clustering"""
        features = []

        for event in events:
            # Extract hour of day
            timestamp = datetime.fromisoformat(event["timestamp"])
            hour = timestamp.hour

            # Extract event type as numerical
            event_type_map = {
                "query": 0,
                "document_access": 1,
                "performance": 2,
                "error": 3,
            }
            event_type_num = event_type_map.get(event.get("type", ""), 4)

            # Extract other features
            features.append(
                [
                    hour,
                    event_type_num,
                    len(event.get("query", "")),
                    event.get("results_found", 0),
                    event.get("latency_ms", 0) / 1000.0,  # Convert to seconds
                ]
            )

        return np.array(features)

    def _extract_query_topic(self, query: str) -> str:
        """Extract main topic from query"""
        # Simple topic extraction - in production, use NLP
        stop_words = {
            "what",
            "how",
            "where",
            "when",
            "why",
            "is",
            "are",
            "the",
            "a",
            "an",
        }
        words = query.lower().split()

        # Filter stop words and get most significant term
        significant_words = [w for w in words if w not in stop_words and len(w) > 3]

        if significant_words:
            return significant_words[0]
        return "general"

    def _calculate_gap_severity(self, failures: List[Dict[str, Any]]) -> float:
        """Calculate severity of a knowledge gap"""
        # Factors: frequency, recency, user diversity
        frequency_score = min(len(failures) / 10.0, 1.0)

        # Recency score
        recent_failures = sum(
            1
            for f in failures
            if (datetime.now() - datetime.fromisoformat(f["timestamp"])).days < 7
        )
        recency_score = recent_failures / len(failures)

        # User diversity
        unique_users = len(set(f.get("user_id", "unknown") for f in failures))
        diversity_score = min(unique_users / 5.0, 1.0)

        # Combined severity
        severity = frequency_score * 0.4 + recency_score * 0.4 + diversity_score * 0.2

        return round(severity, 2)

    def _generate_gap_recommendation(
        self, topic: str, failures: List[Dict[str, Any]]
    ) -> str:
        """Generate recommendation for addressing a knowledge gap"""

        # Analyze query variations
        queries = [f["query"] for f in failures]

        # Simple recommendation logic
        if len(queries) > 10:
            return f"Create comprehensive documentation section for '{topic}' covering common questions"
        elif len(set(queries)) == 1:
            return f"Add specific answer for frequently asked question: '{queries[0]}'"
        else:
            return f"Enhance existing '{topic}' documentation with more examples and use cases"

    # Tool method implementations
    def _track_usage_event(self, event_type: str, event_data: Dict) -> str:
        """Tool method for usage tracking"""
        return (
            f"Tracked {event_type} event with data: {json.dumps(event_data, indent=2)}"
        )

    def _analyze_usage_patterns(self, time_range: str) -> str:
        """Tool method for pattern analysis"""
        return f"Analyzing patterns for time range: {time_range}"

    def _identify_knowledge_gaps(self) -> str:
        """Tool method for gap identification"""
        return "Identifying knowledge gaps based on failed queries and usage patterns"

    def _generate_actionable_insights(self, focus_area: str) -> str:
        """Tool method for insight generation"""
        return f"Generating insights for focus area: {focus_area}"
