import numpy as np
import matplotlib.pyplot as plt


def is_prime(n):
    if n < 2:
        return False

    for i in range(2, int(np.sqrt(n)) + 1):
        if n % i == 0:
            return False

    return True


def move(position, dice):
    new_position = position + dice

    if new_position > 99:
        return 100

    if is_prime(new_position):
        new_position += 1

    if new_position > 99:
        return 100

    return new_position


def complete_turn(start_position):
    result = np.zeros(101)
    active = [(start_position, 1.0)]

    while active:
        position, probability = active.pop()

        for dice in range(1, 7):
            p = probability / 6
            new_position = move(position, dice)

            if new_position == 100:
                result[100] += p
                continue

            if new_position % 13 == 0 and new_position != 0:
                result[new_position] += p
                continue

            if dice == 6:
                active.append((new_position, p))
            else:
                result[new_position] += p

    return result


Q = np.zeros((201, 201))

for position in range(100):
    result = complete_turn(position)

    for new_position in range(101):
        probability = result[new_position]

        if probability == 0:
            continue

        if new_position == 100:
            Q[position, 200] += probability

        elif new_position % 13 == 0 and new_position != 0:
            Q[position, 100 + new_position] += probability

        else:
            Q[position, new_position] += probability


for position in range(100):
    Q[100 + position, position] = 1

Q[200, 200] = 1


np.set_printoptions(precision=4, suppress=True, linewidth=200, threshold=np.inf)

print("Problem 1(a)")
print("Transition Matrix:")
print(Q)

print("Matrix shape:")
print(Q.shape)

print("Row sums:")
print(Q.sum(axis=1))


state = np.zeros(201)
state[0] = 1

before_40 = state.copy()

for turn in range(39):
    before_40 = before_40 @ Q

after_40 = before_40 @ Q

probability_turn_40 = after_40[200] - before_40[200]

print("\nProblem 1(b)")
print("Probability of finishing exactly on turn 40:")
print(probability_turn_40)


alpha_values = np.linspace(-1, 1, 201)
x0_values = np.linspace(-2, 2, 401)

final_states = np.zeros((len(alpha_values), len(x0_values)))

for i, alpha in enumerate(alpha_values):

    x = x0_values.copy()

    for n in range(1000):
        x = np.exp(-5 * x**2) + alpha

    final_states[i] = x


bins = np.linspace(-2, 2, 41)

histograms = np.zeros((len(alpha_values), len(bins) - 1))

for i in range(len(alpha_values)):
    histograms[i], _ = np.histogram(final_states[i], bins=bins)


print("\nProblem 2")

for target_alpha in [-1, -0.5, 0]:

    index = np.argmin(np.abs(alpha_values - target_alpha))

    print("\nAlpha =", alpha_values[index])
    print(histograms[index])


A = np.repeat(alpha_values, len(x0_values))

X = final_states.flatten()

plt.figure(figsize=(10, 6))

plt.scatter(A, X, s=1)

plt.xlabel("alpha")
plt.ylabel("Final state x")
plt.title("Bifurcation Diagram")

plt.show()
