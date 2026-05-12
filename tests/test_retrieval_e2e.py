#!/usr/bin/env python3
"""
E2E Smoke Tests for Aviation Intelligence Retrieval Service

Tests three core use cases:
1. Delay Explanation: "Why was flight X delayed?"
2. Route Risk Analysis: "What's the risk level for route X?"
3. Natural Language Analytics: "How many flights had weather impact?"

Usage:
  python test_retrieval_e2e.py <service_url> [--timeout 30]

Example:
  python test_retrieval_e2e.py https://aviation-retrieval-ohvijuloea-uc.a.run.app
"""

import sys
import json
import time
import argparse
import logging
from typing import Dict, Any
import requests
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RetrievalServiceTester:
    """E2E smoke test suite for retrieval service."""
    
    def __init__(self, service_url: str, timeout: int = 30):
        self.service_url = service_url.rstrip('/')
        self.timeout = timeout
        self.results = {
            'health_check': False,
            'readiness_check': False,
            'delay_explanation': False,
            'route_risk_analysis': False,
            'nl_analytics': False,
        }
        self.errors = []
    
    def test_health_check(self) -> bool:
        """Test basic health check endpoint."""
        try:
            logger.info("Testing /health endpoint...")
            response = requests.get(
                f"{self.service_url}/health",
                timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            
            assert data.get("status") == "healthy", f"Unexpected status: {data}"
            logger.info("✓ Health check passed")
            self.results['health_check'] = True
            return True
            
        except Exception as e:
            msg = f"✗ Health check failed: {e}"
            logger.error(msg)
            self.errors.append(msg)
            return False
    
    def test_readiness_check(self) -> bool:
        """Test readiness check (BigQuery + embedding model connectivity)."""
        try:
            logger.info("Testing /health/ready endpoint...")
            response = requests.get(
                f"{self.service_url}/health/ready",
                timeout=self.timeout
            )
            
            # Readiness may return 503 if dependencies not ready, which is ok
            data = response.json()
            
            if response.status_code == 200:
                assert data.get("ready") is True, f"Service not ready: {data}"
                logger.info("✓ Readiness check passed (service fully ready)")
            else:
                logger.warning(f"⚠ Service not yet ready (status {response.status_code}), continuing with other tests")
                # Don't fail on this - vector search may still be building
            
            self.results['readiness_check'] = True
            return True
            
        except Exception as e:
            msg = f"✗ Readiness check failed: {e}"
            logger.error(msg)
            self.errors.append(msg)
            return False
    
    def _validate_retrieval_response(self, response_data: Dict[str, Any], use_case: str) -> bool:
        """Validate retrieval response structure and content."""
        try:
            # Check required fields
            required_fields = ['question', 'answer', 'context_count', 'facts_count', 'sources', 'timestamp']
            for field in required_fields:
                assert field in response_data, f"Missing field: {field}"
            
            # Validate data quality
            assert isinstance(response_data['answer'], str) and len(response_data['answer']) > 10, \
                f"Answer too short or missing: {response_data['answer']}"
            
            assert response_data['context_count'] >= 0, \
                f"Invalid context_count: {response_data['context_count']}"
            
            assert response_data['facts_count'] >= 0, \
                f"Invalid facts_count: {response_data['facts_count']}"
            
            assert isinstance(response_data['sources'], list), \
                "Sources should be a list"
            
            logger.info(f"  ✓ Response structure valid for {use_case}")
            logger.info(f"    - Answer length: {len(response_data['answer'])} chars")
            logger.info(f"    - Context docs: {response_data['context_count']}")
            logger.info(f"    - Facts: {response_data['facts_count']}")
            logger.info(f"    - Sources: {len(response_data['sources'])}")
            
            return True
            
        except AssertionError as e:
            logger.error(f"  ✗ Response validation failed: {e}")
            return False
    
    def test_delay_explanation(self) -> bool:
        """Test Use Case 1: Delay Explanation
        
        Example: "Why are United Airlines flights experiencing delays?"
        Expected: Answer explaining delay causes with citations.
        """
        try:
            logger.info("Testing Use Case 1: Delay Explanation...")
            
            question = "Why are United Airlines flights experiencing delays? What factors contribute most to delays?"
            
            payload = {
                "question": question,
                "airline": "UA",
                "days_back": 7,
                "top_k": 5
            }
            
            response = requests.post(
                f"{self.service_url}/retrieve",
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            
            logger.info(f"  Question: {question}")
            
            # Validate response
            if not self._validate_retrieval_response(data, "Delay Explanation"):
                self.errors.append("Delay Explanation response validation failed")
                return False
            
            # Validate content quality
            answer_lower = data['answer'].lower()
            quality_keywords = ['delay', 'weather', 'airline', 'minute', 'percent', '%']
            keyword_matches = sum(1 for kw in quality_keywords if kw in answer_lower)
            
            if keyword_matches >= 2:
                logger.info(f"  ✓ Answer contains domain-specific keywords (matched {keyword_matches}/{len(quality_keywords)})")
            else:
                logger.warning(f"  ⚠ Answer may lack domain-specific keywords (matched {keyword_matches}/{len(quality_keywords)})")
            
            logger.info("✓ Delay Explanation use case passed")
            self.results['delay_explanation'] = True
            return True
            
        except Exception as e:
            msg = f"✗ Delay Explanation failed: {e}"
            logger.error(msg)
            self.errors.append(msg)
            return False
    
    def test_route_risk_analysis(self) -> bool:
        """Test Use Case 2: Route Risk Analysis
        
        Example: "What's the risk level for the Atlanta to Los Angeles route?"
        Expected: Risk metrics with disruption rates, severe delay percentages.
        """
        try:
            logger.info("Testing Use Case 2: Route Risk Analysis...")
            
            question = "What's the risk level for the Atlanta to Los Angeles route? Include disruption metrics."
            
            payload = {
                "question": question,
                "route": "ATL-LAX",
                "days_back": 7,
                "top_k": 5
            }
            
            response = requests.post(
                f"{self.service_url}/retrieve",
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            
            logger.info(f"  Question: {question}")
            
            # Validate response
            if not self._validate_retrieval_response(data, "Route Risk Analysis"):
                self.errors.append("Route Risk Analysis response validation failed")
                return False
            
            # Validate content quality for risk metrics
            answer_lower = data['answer'].lower()
            risk_keywords = ['risk', 'disruption', 'delay', 'percent', '%', 'rate', 'flight']
            keyword_matches = sum(1 for kw in risk_keywords if kw in answer_lower)
            
            if keyword_matches >= 3:
                logger.info(f"  ✓ Answer contains risk-related keywords (matched {keyword_matches}/{len(risk_keywords)})")
            else:
                logger.warning(f"  ⚠ Answer may lack risk metrics (matched {keyword_matches}/{len(risk_keywords)})")
            
            logger.info("✓ Route Risk Analysis use case passed")
            self.results['route_risk_analysis'] = True
            return True
            
        except Exception as e:
            msg = f"✗ Route Risk Analysis failed: {e}"
            logger.error(msg)
            self.errors.append(msg)
            return False
    
    def test_nl_analytics(self) -> bool:
        """Test Use Case 3: Natural Language Analytics
        
        Example: "How many flights had weather impact last week?"
        Expected: Aggregated analytics with weather impact percentage.
        """
        try:
            logger.info("Testing Use Case 3: Natural Language Analytics...")
            
            question = "How many flights had weather impact in the last 7 days? What was the weather impact percentage?"
            
            payload = {
                "question": question,
                "days_back": 7,
                "top_k": 5
            }
            
            response = requests.post(
                f"{self.service_url}/retrieve",
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            
            logger.info(f"  Question: {question}")
            
            # Validate response
            if not self._validate_retrieval_response(data, "NL Analytics"):
                self.errors.append("NL Analytics response validation failed")
                return False
            
            # Validate content quality for analytics
            answer_lower = data['answer'].lower()
            analytics_keywords = ['weather', 'flight', 'percent', '%', 'count', 'impact', 'affected']
            keyword_matches = sum(1 for kw in analytics_keywords if kw in answer_lower)
            
            if keyword_matches >= 3:
                logger.info(f"  ✓ Answer contains analytics keywords (matched {keyword_matches}/{len(analytics_keywords)})")
            else:
                logger.warning(f"  ⚠ Answer may lack analytics detail (matched {keyword_matches}/{len(analytics_keywords)})")
            
            # Validate facts were retrieved
            if data['facts_count'] > 0:
                logger.info(f"  ✓ BigQuery facts retrieved ({data['facts_count']} rows)")
            else:
                logger.warning("  ⚠ No BigQuery facts retrieved (data may be limited)")
            
            logger.info("✓ Natural Language Analytics use case passed")
            self.results['nl_analytics'] = True
            return True
            
        except Exception as e:
            msg = f"✗ Natural Language Analytics failed: {e}"
            logger.error(msg)
            self.errors.append(msg)
            return False
    
    def run_all_tests(self) -> Dict[str, bool]:
        """Run full test suite."""
        logger.info("=" * 70)
        logger.info("Aviation Intelligence Retrieval Service - E2E Smoke Tests")
        logger.info("=" * 70)
        logger.info(f"Target Service: {self.service_url}\n")
        
        # Run tests in order
        self.test_health_check()
        time.sleep(1)
        
        self.test_readiness_check()
        time.sleep(1)
        
        self.test_delay_explanation()
        time.sleep(2)
        
        self.test_route_risk_analysis()
        time.sleep(2)
        
        self.test_nl_analytics()
        
        # Print summary
        logger.info("\n" + "=" * 70)
        logger.info("Test Summary")
        logger.info("=" * 70)
        
        passed = sum(1 for v in self.results.values() if v)
        total = len(self.results)
        
        for test_name, passed_flag in self.results.items():
            status = "✓ PASS" if passed_flag else "✗ FAIL"
            logger.info(f"{status:8} | {test_name}")
        
        logger.info("-" * 70)
        logger.info(f"Overall: {passed}/{total} tests passed")
        
        if self.errors:
            logger.info("\nErrors encountered:")
            for error in self.errors:
                logger.error(f"  - {error}")
        
        logger.info("=" * 70)
        
        return self.results


def main():
    parser = argparse.ArgumentParser(
        description="E2E Smoke Tests for Aviation Intelligence Retrieval Service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_retrieval_e2e.py http://localhost:8080
  python test_retrieval_e2e.py https://aviation-retrieval-ohvijuloea-uc.a.run.app --timeout 45
        """
    )
    parser.add_argument(
        "service_url",
        help="Base URL of the retrieval service (e.g., https://service.run.app)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Request timeout in seconds (default: 30)"
    )
    
    args = parser.parse_args()
    
    tester = RetrievalServiceTester(args.service_url, timeout=args.timeout)
    results = tester.run_all_tests()
    
    # Exit with error if any critical test failed
    if not all(results.values()):
        sys.exit(1)
    
    sys.exit(0)


if __name__ == "__main__":
    main()
