#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib/core';
import { AgentAutoSystemStackStack } from '../lib/agent-auto-system-stack-stack';

const app = new cdk.App();
new AgentAutoSystemStackStack(app, 'AgentAutoSystemStackStack', {
  // Use the account/region from the deploy environment so the VPC resolves
  // two real Availability Zones (env-agnostic stacks only see two dummy AZs).
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION,
  },
});
