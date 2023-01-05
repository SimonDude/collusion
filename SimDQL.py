import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import math
import gym
import random
import numpy as np
import matplotlib.pyplot as plt
from mesa import Agent, Model
from mesa.time import BaseScheduler


def demand(p_i, rest, num):
    d = 1 - p_i + ((1 / num) / (num - 1)) * rest * num
    return d


def profit(p_i, d):
    pi = p_i * d
    return pi


env = gym.make('CartPole-v1')
observation_space = env.observation_space.shape[0]
action_space = env.action_space.n

steps = 1000 * 500
n_firms = 2
runs = 2
multirun = True
LEARNING_RATE = 0.0001
MEM_SIZE = 10000
BATCH_SIZE = 64
GAMMA = 0.95
EXPLORATION_MAX = 1.0
EXPLORATION_DECAY = 0.999
EXPLORATION_MIN = 0.001

FC1_DIMS = 1024
FC2_DIMS = 512
DEVICE = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

best_reward = 0
average_reward = 0
episode_number = []
average_reward_number = []

np.random.seed(66)
price_hist = np.zeros((steps, n_firms * (runs if multirun else 1)))
profit_hist = np.zeros((steps, n_firms * (runs if multirun else 1)))
demand_hist = np.zeros((steps, n_firms * (runs if multirun else 1)))


class Firm(Agent):

    def __init__(self, unique_id, model):
        super().__init__(unique_id, model)
        self.price = np.random.uniform(0, 1)
        self.profit = np.zeros((steps, 1))
        self.demand = np.zeros((steps, 1))
        self.price_list = np.zeros((steps, 1))
        self.price_list[0:2] = np.random.uniform(0, 1, 2).reshape(2, 1)
        self.state = 0
        self.action = 0
        self.memory = ReplayBuffer()
        self.exploration_rate = EXPLORATION_MAX
        self.network = Network()

    def choose_action(self, observation):
        if random.random() < self.exploration_rate:
            return env.action_space.sample()

        state = torch.tensor(observation).float().detach()
        state = state.to(DEVICE)
        state = state.unsqueeze(0)
        q_values = self.network(state)
        return torch.argmax(q_values).item()

    def learn(self):
        if self.memory.mem_count < BATCH_SIZE:
            return

        states, actions, rewards, states_, dones = self.memory.sample()
        states = torch.tensor(states, dtype=torch.float32).to(DEVICE)
        actions = torch.tensor(actions, dtype=torch.long).to(DEVICE)
        rewards = torch.tensor(rewards, dtype=torch.float32).to(DEVICE)
        states_ = torch.tensor(states_, dtype=torch.float32).to(DEVICE)
        dones = torch.tensor(dones, dtype=torch.bool).to(DEVICE)
        batch_indices = np.arange(BATCH_SIZE, dtype=np.int64)

        q_values = self.network(states)
        next_q_values = self.network(states_)

        predicted_value_of_now = q_values[batch_indices, actions]
        predicted_value_of_future = torch.max(next_q_values, dim=1)[0]

        q_target = rewards + GAMMA * predicted_value_of_future * dones

        loss = self.network.loss(q_target, predicted_value_of_now)
        self.network.optimizer.zero_grad()
        loss.backward()
        self.network.optimizer.step()

        self.exploration_rate *= EXPLORATION_DECAY
        self.exploration_rate = max(EXPLORATION_MIN, self.exploration_rate)

    def returning_epsilon(self):
        return self.exploration_rate

    def act(self, rest):
        self.state = np.searchsorted(states, rest)

        if model.epsilon > np.random.uniform(0, 1):
            action = np.random.choice(actions, 1)
        else:
            action = actions[np.argmax(self.qmatrix[self.state, :])]

        self.price = action
        self.action = np.searchsorted(actions, self.price)
        self.price_list[model.period] = action
        model.prices[model.period, self.unique_id] = action

    def update(self, p_i, rest, rest_1):
        action = np.searchsorted(actions, p_i)
        state = np.searchsorted(states, rest)
        next_state = np.searchsorted(states, rest_1)

        pot_profit = p_i * demand(p_i, rest_1, n_firms)
        new_est = self.profit[model.period - 2] + gamma * pot_profit + gamma ** 2 * np.max(self.qmatrix[next_state, :])
        new_val = (1 - alpha) * self.qmatrix[state, action] + alpha * new_est
        return new_val

    def observe(self, p_i, rest, rest_1):
        action = np.searchsorted(actions, p_i)
        state = np.searchsorted(states, rest)

        self.qmatrix[state, action] = self.update(p_i, rest, rest_1)


class CollusionModel(Model):
    def __init__(self, N):
        self.state_space = 1
        self.action_space = 1
        self.num_agents = N
        self.period = 2
        # self.max_demand = max_demand
        self.demand_list = []
        self.prices = np.zeros([steps, n_firms])
        self.epsilon = 1
        self.theta = 1 - np.power(0.001, 1 / (0.5 * steps))
        # Create agents
        self.schedule = BaseScheduler(self)
        for i in range(self.num_agents):
            a = Firm(i, self)
            self.schedule.add(a)
        for a in self.schedule.agents:
            self.prices[0:2, a.unique_id] = a.price_list[0:2].reshape(2, )
        for a in self.schedule.agents:
            rest = np.mean(np.delete(self.prices[0:2, :], a.unique_id, axis=1),
                           axis=1)  # Here is where we lose information due to rounding the mean.
            a.demand[0:2] = demand(a.price_list[0:2].reshape(2, ), rest, n_firms).reshape(2, 1)
            a.profit[0:2] = a.demand[0:2] * a.price_list[0:2]

    def step(self):
        for a in self.schedule.agents:
            rest = np.mean(np.delete(self.prices[self.period - 2, :],
                                     a.unique_id))  # Here is where we lose information due to rounding the mean.
            rest_1 = np.mean(np.delete(self.prices[self.period - 1, :],
                                       a.unique_id))  # Here is where we lose information due to rounding the mean.

            a.observe(a.price_list[self.period - 2], rest, rest_1)
            a.act(np.mean(np.delete(self.prices[self.period, :],
                                    a.unique_id)))  # Here is where we lose information due to rounding the mean.

        for a in self.schedule.agents:
            rest = np.mean(np.delete(self.prices[self.period, :], a.unique_id))
            a.demand[self.period] = demand(a.price_list[self.period], rest, n_firms)
            a.profit[self.period] = a.demand[self.period] * a.price_list[self.period]

        self.epsilon = (1 - self.theta) ** self.period
        self.period += 1
        if self.period == steps:
            agent_id = 0
            for a in self.schedule.agents:
                for time in range(steps - 2, steps):
                    rest = np.mean(np.delete(self.prices[time, :],
                                             a.unique_id))  # Here is where we lose information due to rounding the mean.
                    a.demand[time] = demand(a.price_list[time], rest, n_firms)
                    a.profit[time] = a.demand[time] * a.price_list[time]

                price_hist[:, agent_id + j * n_firms] = a.price_list.reshape(-1)
                demand_hist[:, agent_id + j * n_firms] = a.demand.reshape(-1)
                profit_hist[:, agent_id + j * n_firms] = a.profit.reshape(-1)
                agent_id += 1


class Network(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.input_shape = env.observation_space.shape
        self.action_space = action_space

        self.fc1 = nn.Linear(*self.input_shape, FC1_DIMS)
        self.fc2 = nn.Linear(FC1_DIMS, FC2_DIMS)
        self.fc3 = nn.Linear(FC2_DIMS, self.action_space)

        self.optimizer = optim.Adam(self.parameters(), lr=LEARNING_RATE)
        self.loss = nn.MSELoss()
        self.to(DEVICE)

    def forward(self, x):
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = self.fc3(x)

        return x


class ReplayBuffer:
    def __init__(self):
        self.mem_count = 0

        self.states = np.zeros((MEM_SIZE, *env.observation_space.shape), dtype=np.float32)
        self.actions = np.zeros(MEM_SIZE, dtype=np.int64)
        self.rewards = np.zeros(MEM_SIZE, dtype=np.float32)
        self.states_ = np.zeros((MEM_SIZE, *env.observation_space.shape), dtype=np.float32)
        self.dones = np.zeros(MEM_SIZE, dtype=np.bool)

    def add(self, state, action, reward, state_, done):
        mem_index = self.mem_count % MEM_SIZE

        self.states[mem_index] = state
        self.actions[mem_index] = action
        self.rewards[mem_index] = reward
        self.states_[mem_index] = state_
        self.dones[mem_index] = 1 - done

        self.mem_count += 1

    def sample(self):
        MEM_MAX = min(self.mem_count, MEM_SIZE)
        batch_indices = np.random.choice(MEM_MAX, BATCH_SIZE, replace=True)

        states = self.states[batch_indices]
        actions = self.actions[batch_indices]
        rewards = self.rewards[batch_indices]
        states_ = self.states_[batch_indices]
        dones = self.dones[batch_indices]

        return states, actions, rewards, states_, dones


class DQN_Solver:
    def __init__(self):
        self.memory = ReplayBuffer()
        self.exploration_rate = EXPLORATION_MAX
        self.network = Network()

    def choose_action(self, observation):
        if random.random() < self.exploration_rate:
            return env.action_space.sample()

        state = torch.tensor(observation).float().detach()
        state = state.to(DEVICE)
        state = state.unsqueeze(0)
        q_values = self.network(state)
        return torch.argmax(q_values).item()

    def learn(self):
        if self.memory.mem_count < BATCH_SIZE:
            return

        states, actions, rewards, states_, dones = self.memory.sample()
        states = torch.tensor(states, dtype=torch.float32).to(DEVICE)
        actions = torch.tensor(actions, dtype=torch.long).to(DEVICE)
        rewards = torch.tensor(rewards, dtype=torch.float32).to(DEVICE)
        states_ = torch.tensor(states_, dtype=torch.float32).to(DEVICE)
        dones = torch.tensor(dones, dtype=torch.bool).to(DEVICE)
        batch_indices = np.arange(BATCH_SIZE, dtype=np.int64)

        q_values = self.network(states)
        next_q_values = self.network(states_)

        predicted_value_of_now = q_values[batch_indices, actions]
        predicted_value_of_future = torch.max(next_q_values, dim=1)[0]

        q_target = rewards + GAMMA * predicted_value_of_future * dones

        loss = self.network.loss(q_target, predicted_value_of_now)
        self.network.optimizer.zero_grad()
        loss.backward()
        self.network.optimizer.step()

        self.exploration_rate *= EXPLORATION_DECAY
        self.exploration_rate = max(EXPLORATION_MIN, self.exploration_rate)

    def returning_epsilon(self):
        return self.exploration_rate


agent = DQN_Solver()
model = CollusionModel(n_firms)

for i in range(1, steps):
    model.__init__()
    state = env.reset()[0]
    state = np.reshape(state, [1, observation_space])
    score = 0

    while True:
        # env.render()
        action = agent.choose_action(state)
        state_, reward, done, info = env.step(action)[0:4]
        state_ = np.reshape(state_, [1, observation_space])
        agent.memory.add(state, action, reward, state_, done)
        agent.learn()
        state = state_
        score += reward

        if done:
            if score > best_reward:
                best_reward = score
            average_reward += score
            print("Episode {} Average Reward {} Best Reward {} Last Reward {} Epsilon {}".format(i, average_reward / i,
                                                                                                 best_reward, score,
                                                                                                 agent.returning_epsilon()))
            break

        episode_number.append(i)
        average_reward_number.append(average_reward / i)

plt.plot(episode_number, average_reward_number)
plt.show()