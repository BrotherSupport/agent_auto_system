import * as cdk from 'aws-cdk-lib/core';
import { Template, Match } from 'aws-cdk-lib/assertions';
import * as AgentAutoSystemStack from '../lib/agent-auto-system-stack-stack';

function synth() {
  const app = new cdk.App();
  const stack = new AgentAutoSystemStack.AgentAutoSystemStackStack(app, 'TestStack', {
    env: { account: '123456789012', region: 'us-east-1' },
  });
  return Template.fromStack(stack);
}

test('runs a single Fargate task behind a public ALB', () => {
  const template = synth();

  // Exactly one always-on task (single SQLite writer / in-process registry).
  template.hasResourceProperties('AWS::ECS::Service', {
    DesiredCount: 1,
    DeploymentConfiguration: Match.objectLike({
      MinimumHealthyPercent: 0,
      MaximumPercent: 100,
    }),
  });

  template.hasResourceProperties('AWS::ElasticLoadBalancingV2::LoadBalancer', {
    Scheme: 'internet-facing',
  });
});

test('task sizing and ephemeral storage match the design', () => {
  const template = synth();

  template.hasResourceProperties('AWS::ECS::TaskDefinition', {
    Cpu: '512',
    Memory: '1024',
    EphemeralStorage: { SizeInGiB: 21 },
  });
});

test('ALB health check targets /health', () => {
  const template = synth();

  template.hasResourceProperties('AWS::ElasticLoadBalancingV2::TargetGroup', {
    HealthCheckPath: '/health',
  });
});

test('no NAT Gateway and no Secrets Manager (phase-1 simplicity)', () => {
  const template = synth();

  template.resourceCountIs('AWS::EC2::NatGateway', 0);
  template.resourceCountIs('AWS::SecretsManager::Secret', 0);
});
